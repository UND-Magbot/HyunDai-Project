"""
Convoy(대열) 작업 모드 서비스
- 시작 버튼 1번으로 로봇이 순차 출발
- 충전소 → 진입경로 → WORK1~WORK6 무한 반복
- 1열 유지 (앞 로봇보다 한 구간 뒤 대기)
- 그레이스풀 정지: 모든 로봇 WORK1 복귀 → C3→C2→C1 순서로 충전소 귀환
"""
import json
import math
import os
import struct
import time
import threading
import logging
from typing import Optional

from app.database import SessionLocal
from app.models.map import MapPOI, RobotMap, ConvoySavedState, ConvoyRuntime
from app.models.robot import Robot
from app.robot_api.robot_map_service import set_chassis_pose

# robot_task_service에서 재사용하는 함수/상태
from app.robot_api.robot_task_service import (
    send_move,
    send_charge,
    cancel_and_verify,
    _create_planning_ws,
    _wait_for_move_ws,
    _wait_for_move_http,
    _get_battery_percentage,
    _get_move_lock,
    _lock as _task_lock,
    _confirm_events,
    _run_info,
    _stuck_states,
    RECOVERY_DELAY,
)
from websocket import WebSocketException
from app.crud.activity_log import log_activity

logger = logging.getLogger(__name__)

# ─── BackEnd 루트 디렉토리 (static 파일 접근용) ─────────────────────────────────
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))


# ─── SVG→World 좌표 변환 ────────────────────────────────────────────────────────

def _get_png_dimensions(image_url: str) -> tuple[int, int] | None:
    """이미지 URL에서 PNG 가로/세로 크기를 읽어온다 (헤더 24바이트만 파싱)"""
    if not image_url:
        return None

    # 로컬 파일 (/static/maps/...)
    if image_url.startswith("/static/"):
        local_path = os.path.join(_BACKEND_DIR, image_url.lstrip("/"))
        if os.path.exists(local_path):
            with open(local_path, "rb") as f:
                header = f.read(24)
            if len(header) >= 24 and header[:8] == b"\x89PNG\r\n\x1a\n":
                w, h = struct.unpack(">II", header[16:24])
                return w, h

    return None


def _ensure_world_coords(db, pois_list: list, robot_id: int):
    """POI 리스트의 world_x/world_y가 None이면 맵 메타데이터로 자동 변환.
    detached POI 객체의 속성을 직접 수정한다 (DB에는 반영 안 됨).
    """
    need_convert = [p for p in pois_list if p.world_x is None or p.world_y is None]
    if not need_convert:
        return

    # 맵 메타데이터 조회
    map_id = need_convert[0].map_id
    robot_map = db.query(RobotMap).filter(RobotMap.id == map_id).first()
    if not robot_map or robot_map.grid_resolution <= 0:
        logger.warning(f"[Robot {robot_id}] 맵 {map_id} 메타데이터 없음 — 좌표 변환 불가")
        return

    dims = _get_png_dimensions(robot_map.image_url)
    if not dims:
        logger.warning(f"[Robot {robot_id}] 맵 이미지 크기 확인 불가: {robot_map.image_url}")
        return

    img_w, img_h = dims
    half_w = img_w / 2
    half_h = img_h / 2
    ox = robot_map.grid_origin_x
    oy = robot_map.grid_origin_y
    res = robot_map.grid_resolution

    for poi in need_convert:
        poi.world_x = (poi.x + half_w) * res + ox
        poi.world_y = (half_h - poi.y) * res + oy


# ─── 배터리 기반 위치 재배치 ──────────────────────────────────────────────────

# 위치 우선순위 (출발 순서): C1 → C2 → C3 → W1 (배터리 적은순 배정)
_POSITION_ORDER = ["C1", "C2", "C3", "W1", "W2"]


def _reassign_convoy_positions(
    map_id: int | None = None,
    excluded_positions: set[str] | None = None,
):
    """전체 convoy 로봇 배터리 조회 → 위치 재배치 (DB 업데이트)
    excluded_positions: hot swap 등으로 이미 점유된 위치 — 재배치 대상에서 제외
    """
    with _convoy_lock:
        robots = _convoy_robots[:]

    if not robots:
        return

    # 배터리: 캐시 우선, 없으면 실시간 조회, 실패 시 기본 50%
    battery_levels = []
    for rc in robots:
        rid = rc["robot_id"]
        cached = _convoy_battery_cache.get(rid)
        if cached is not None:
            pct = cached
        else:
            pct = _get_battery_percentage(rc["ip"])
            if pct is not None:
                _convoy_battery_cache[rid] = pct
            else:
                pct = 50.0
                logger.info(f"[Convoy 재배치] 로봇 {rid} 배터리 조회 실패 — 기본 50%")
        battery_levels.append((rid, pct))

    # 배터리 오름차순 정렬 (낮은 것부터 충전소 배정)
    battery_levels.sort(key=lambda x: x[1])

    # 점유된 위치 제외 후 배정 가능 위치 결정
    # 실제 재배치 대상(온라인 로봇만)이 아닌 모든 로봇의 충전소/대기지점을 제외
    reassign_robot_ids = {rid for rid, _ in battery_levels}
    db_check = SessionLocal()
    outside_used: set[str] = set()
    try:
        all_robots = db_check.query(Robot).filter(Robot.is_active == True).all()
        poi_ids = set()
        for r in all_robots:
            if r.id not in reassign_robot_ids:
                # 재배치 대상이 아닌 로봇 → 점유 위치 제외
                if r.charging_id:
                    poi_ids.add(r.charging_id)
                if r.standby_id:
                    poi_ids.add(r.standby_id)
        if poi_ids:
            pois = db_check.query(MapPOI).filter(MapPOI.id.in_(poi_ids)).all()
            outside_used = {p.name for p in pois}
    except Exception as e:
        logger.warning(f"[Convoy 재배치] 외부 로봇 점유 위치 조회 실패: {e}")
    finally:
        db_check.close()

    excluded = (excluded_positions or set()) | outside_used
    available = [p for p in _POSITION_ORDER if p not in excluded]
    positions = available[:len(battery_levels)]
    logger.info(f"[Convoy 재배치] 대상: {[rid for rid,_ in battery_levels]}, "
                f"제외: {excluded}, 가용: {available}, 배정: {positions}")

    db = SessionLocal()
    try:
        # 배정된 로봇 ID 추적
        assigned_rids = set()
        for (rid, pct), pos_name in zip(battery_levels, positions):
            robot = db.query(Robot).filter(Robot.id == rid).first()
            if not robot:
                continue

            filters = [MapPOI.name == pos_name, MapPOI.is_active == True]
            if map_id is not None:
                filters.append(MapPOI.map_id == map_id)
            poi = db.query(MapPOI).filter(*filters).first()
            if not poi:
                logger.warning(f"[Convoy 재배치] POI '{pos_name}' 없음 (map_id={map_id})")
                continue

            if pos_name.startswith("W"):
                robot.standby_id = poi.id
                robot.charging_id = None
            else:
                robot.charging_id = poi.id
                robot.standby_id = None
            assigned_rids.add(rid)

        # 배정 안 된 로봇 → 기존 위치 클리어 (중복 방지)
        for (rid, pct) in battery_levels:
            if rid not in assigned_rids:
                robot = db.query(Robot).filter(Robot.id == rid).first()
                if robot:
                    logger.warning(f"[Convoy 재배치] 로봇 {rid} 배정 위치 없음 — 기존 위치 클리어")
                    robot.charging_id = None
                    robot.standby_id = None

        db.commit()
        reassign_desc = ", ".join(
            f"로봇{rid}({pct:.0f}%)→{pos}"
            for (rid, pct), pos in zip(battery_levels, positions)
        )
        log_activity("system", "convoy_reassign",
                     f"Convoy 위치 재배치 완료 ({reassign_desc})",
                     source="_reassign_convoy_positions")
    except Exception as e:
        db.rollback()
        logger.error(f"[Convoy 재배치] DB 업데이트 실패: {e}")
    finally:
        db.close()


# ─── Convoy 전역 상태 ──────────────────────────────────────────────────────────

_convoy_lock = threading.Lock()
_convoy_phase: str = "idle"  # idle | entering | running | returning | stopped | error
_convoy_is_resume: bool = False                            # 재개 모드 여부 (entering 오버레이 구분용)
_convoy_stop_event: Optional[threading.Event] = None
_convoy_graceful_event: Optional[threading.Event] = None
_convoy_robots: list[dict] = []  # [{robot_id, ip, entry_names, return_names, ...}]
_convoy_robot_status: dict[int, dict] = {}  # {robot_id: {status, current_poi, loop, ...}}
_convoy_node_positions: dict[int, int | None] = {}  # {robot_id: 현재 노드 인덱스(0~N-1) or None}
_convoy_reassign_done = threading.Event()    # 그레이스풀 재배치 1회 실행 보장
_convoy_hot_swap_lock = threading.Lock()     # hot swap 재배치 동시 실행 방지
_convoy_standby_pool: list[dict] = []        # 대기 로봇 풀 (hot swap용)
_convoy_work_poi_names: list[str] = []       # standby 투입 시 재사용
_convoy_stop_names: list[str] = []           # standby 투입 시 재사용
_convoy_return_requested: set[int] = set()   # 시간 기반 복귀 요청된 robot_id
_convoy_hourly_timer: Optional[threading.Timer] = None  # 1시간 배터리 체크 타이머
_convoy_hotswap_threads: list[threading.Thread] = []    # hot swap으로 투입된 워커 스레드 목록
_battery_rotation_timer: Optional[threading.Timer] = None  # 대기 배터리 로테이션 타이머
_battery_rotation_stop = threading.Event()  # 로테이션 중지 플래그
_charging_start_time: dict[int, float] = {}  # {robot_id: 충전 시작 시각} — 오래된 순 정렬용
_convoy_map_id: int | None = None                        # 현재 convoy 작업 맵 ID
_fire_event = threading.Event()                           # 화재 경보 이벤트
_convoy_battery_cache: dict[int, float] = {}               # robot_id → 배터리 % 캐시
_convoy_return_events: dict[int, threading.Event] = {}     # robot_id → 개별 복귀 이벤트 (순차 복귀용)
_convoy_all_arrived = threading.Event()                    # 재개 모드: 전원 도착 → 5초 후 작업 시작
_convoy_countdown_until: float | None = None               # 카운트다운 종료 시각 (time.time() 기준)

CONVOY_BATTERY_CHECK_INTERVAL = 300  # 기본 5분(초) — DB convoy_configs.battery_check_interval(분)로 override됨
_convoy_flush_timer: Optional[threading.Timer] = None
CONVOY_FLUSH_INTERVAL = 3  # DB 플러시 주기(초)


def _flush_convoy_state_to_db():
    """메모리 convoy 상태를 DB에 주기적으로 저장 (이중화용)"""
    global _convoy_flush_timer
    if _convoy_phase == "idle":
        # idle이면 DB 런타임 레코드 삭제
        try:
            db = SessionLocal()
            db.query(ConvoyRuntime).delete()
            db.commit()
            db.close()
        except Exception:
            pass
        return

    try:
        db = SessionLocal()
        rt = db.query(ConvoyRuntime).first()
        if not rt:
            rt = ConvoyRuntime()
            db.add(rt)

        with _convoy_lock:
            rt.phase = _convoy_phase
            rt.is_resume = _convoy_is_resume
            rt.map_id = _convoy_map_id
            rt.robots_json = json.dumps([
                {k: v for k, v in r.items() if k != "thread"}
                for r in _convoy_robots
            ], ensure_ascii=False)
            rt.standby_pool_json = json.dumps([
                {k: v for k, v in r.items() if k != "thread"}
                for r in _convoy_standby_pool
            ], ensure_ascii=False)
            rt.node_positions_json = json.dumps(
                {str(k): v for k, v in _convoy_node_positions.items()}
            )
            rt.robot_status_json = json.dumps(
                {str(k): v for k, v in _convoy_robot_status.items()},
                ensure_ascii=False
            )
            rt.work_poi_names_json = json.dumps(_convoy_work_poi_names, ensure_ascii=False)
            rt.stop_names_json = json.dumps(_convoy_stop_names, ensure_ascii=False)
            rt.battery_cache_json = json.dumps(
                {str(k): v for k, v in _convoy_battery_cache.items()}
            )
            rt.return_requested_json = json.dumps(list(_convoy_return_requested))

            # _run_info에서 convoy 로봇만 추출
            convoy_robot_ids = {r["robot_id"] for r in _convoy_robots} | {r["robot_id"] for r in _convoy_standby_pool}
            ri = {str(k): v for k, v in _run_info.items() if k in convoy_robot_ids}
            rt.run_info_json = json.dumps(ri, ensure_ascii=False)

        db.commit()
        db.close()
    except Exception as e:
        logger.warning(f"[Convoy] DB 플러시 실패: {e}")

    # 다음 플러시 예약
    if _convoy_phase != "idle":
        _convoy_flush_timer = threading.Timer(CONVOY_FLUSH_INTERVAL, _flush_convoy_state_to_db)
        _convoy_flush_timer.daemon = True
        _convoy_flush_timer.start()


def _start_convoy_flush():
    """convoy 시작 시 주기적 DB 플러시 시작"""
    global _convoy_flush_timer
    if _convoy_flush_timer:
        _convoy_flush_timer.cancel()
    _convoy_flush_timer = threading.Timer(CONVOY_FLUSH_INTERVAL, _flush_convoy_state_to_db)
    _convoy_flush_timer.daemon = True
    _convoy_flush_timer.start()


def _stop_convoy_flush():
    """convoy 종료 시 DB 플러시 중지 + 런타임 레코드 삭제"""
    global _convoy_flush_timer
    if _convoy_flush_timer:
        _convoy_flush_timer.cancel()
        _convoy_flush_timer = None
    try:
        db = SessionLocal()
        db.query(ConvoyRuntime).delete()
        db.commit()
        db.close()
    except Exception:
        pass


def load_convoy_state_from_db() -> bool:
    """서버 시작 시 DB에서 convoy 상태 복원 (이중화 Standby 인계용)
    Returns: True if state was loaded, False if no state found
    """
    global _convoy_phase, _convoy_is_resume, _convoy_map_id
    global _convoy_work_poi_names, _convoy_stop_names

    try:
        db = SessionLocal()
        rt = db.query(ConvoyRuntime).first()
        if not rt or rt.phase == "idle":
            db.close()
            return False

        with _convoy_lock:
            _convoy_phase = rt.phase
            _convoy_is_resume = rt.is_resume
            _convoy_map_id = rt.map_id

            _convoy_robots.clear()
            _convoy_robots.extend(json.loads(rt.robots_json or "[]"))

            _convoy_standby_pool.clear()
            _convoy_standby_pool.extend(json.loads(rt.standby_pool_json or "[]"))

            np = json.loads(rt.node_positions_json or "{}")
            _convoy_node_positions.clear()
            _convoy_node_positions.update({int(k): v for k, v in np.items()})

            rs = json.loads(rt.robot_status_json or "{}")
            _convoy_robot_status.clear()
            _convoy_robot_status.update({int(k): v for k, v in rs.items()})

            _convoy_work_poi_names.clear()
            _convoy_work_poi_names.extend(json.loads(rt.work_poi_names_json or "[]"))

            _convoy_stop_names.clear()
            _convoy_stop_names.extend(json.loads(rt.stop_names_json or "[]"))

            bc = json.loads(rt.battery_cache_json or "{}")
            _convoy_battery_cache.clear()
            _convoy_battery_cache.update({int(k): v for k, v in bc.items()})

            rr = json.loads(rt.return_requested_json or "[]")
            _convoy_return_requested.clear()
            _convoy_return_requested.update(rr)

            ri = json.loads(rt.run_info_json or "{}")
            for k, v in ri.items():
                _run_info[int(k)] = v

        db.close()
        logger.info(f"[Convoy] DB에서 런타임 상태 복원: phase={_convoy_phase}, robots={len(_convoy_robots)}")
        return True
    except Exception as e:
        logger.warning(f"[Convoy] DB 상태 복원 실패: {e}")
        return False


# ─── Convoy 상태 조회 ──────────────────────────────────────────────────────────

def get_convoy_status() -> dict:
    """convoy 전체 상태 + 개별 로봇 상태 반환"""
    with _convoy_lock:
        robots = []
        for rc in _convoy_robots:
            rid = rc["robot_id"]
            rs = _convoy_robot_status.get(rid, {"status": "idle"})
            node_position = _convoy_node_positions.get(rid)
            robots.append({"robot_id": rid, "node_position": node_position, **rs})
        # 카운트다운 잔여 시간 (전원 도착 후 작업 시작 대기)
        countdown = None
        if _convoy_countdown_until is not None:
            remaining = _convoy_countdown_until - time.time()
            countdown = max(0, int(remaining + 0.5))  # 반올림

        return {
            "phase": _convoy_phase,
            "robots": robots,
            "countdown": countdown,
            "is_resume": _convoy_is_resume,
        }


# ─── Convoy 시작 ───────────────────────────────────────────────────────────────

def start_convoy(
    robots_config: list[dict],
    work_poi_names: list[str],
    stop_names: list[str],
    standby_robots: list[dict] | None = None,
) -> tuple[bool, str]:
    """Convoy 대열 작업 시작

    robots_config: 즉시 출발할 로봇 목록 (최대 4대)
    standby_robots: 대기 풀 로봇 목록 (배터리 부족 시 자동 투입)
    work_poi_names: ["WORK1","WORK2","WORK3","WORK4","WORK5","WORK6"]
    stop_names: ["WORK2","WORK4"]
    """
    global _convoy_phase, _convoy_stop_event, _convoy_graceful_event
    global _convoy_robots, _convoy_robot_status, _convoy_node_positions
    global _convoy_standby_pool, _convoy_work_poi_names, _convoy_stop_names
    global _convoy_hotswap_threads, _convoy_map_id, _convoy_return_events
    global _convoy_is_resume

    with _convoy_lock:
        if _convoy_phase not in ("idle", "stopped", "error"):
            return False, f"이미 convoy 실행 중입니다 (phase={_convoy_phase})"

        _convoy_phase = "entering"
        _convoy_is_resume = False
        _convoy_stop_event = threading.Event()
        _convoy_graceful_event = threading.Event()
        _convoy_robots = robots_config[:]
        _convoy_robot_status = {rc["robot_id"]: {"status": "waiting"} for rc in robots_config}
        _convoy_node_positions.clear()
        _convoy_reassign_done.clear()  # 재배치 플래그 초기화
        _fire_event.clear()  # 화재 이벤트 초기화
        _convoy_standby_pool = list(standby_robots) if standby_robots else []
        _convoy_work_poi_names = work_poi_names[:]
        _convoy_stop_names = stop_names[:]
        _convoy_return_requested.clear()
        _convoy_hotswap_threads.clear()
        _convoy_map_id = None  # 워커 시작 후 work_pois에서 설정됨
        _convoy_return_events = {rc["robot_id"]: threading.Event() for rc in robots_config}
        _convoy_all_arrived.clear()

    # DB에서 배터리 체크 주기 읽기
    global CONVOY_BATTERY_CHECK_INTERVAL
    try:
        from app.models.map import ConvoyConfig as _ConvoyConfig
        _db = SessionLocal()
        _cfg = _db.query(_ConvoyConfig).filter(_ConvoyConfig.is_active == True).first()
        if _cfg and _cfg.battery_check_interval:
            CONVOY_BATTERY_CHECK_INTERVAL = _cfg.battery_check_interval * 60
        _db.close()
    except Exception:
        pass

    # 오케스트레이터 스레드 시작
    t = threading.Thread(
        target=_convoy_orchestrator,
        args=(robots_config, work_poi_names, stop_names),
        daemon=True,
        name="convoy-orchestrator",
    )
    t.start()
    _start_convoy_flush()
    robot_ids = [rc['robot_id'] for rc in robots_config]
    robot_names = [rc.get('robot_name') or f"로봇 {rc['robot_id']}" for rc in robots_config]
    logger.info(f"[Convoy] 오케스트레이터 시작 — 로봇: {robot_ids}, 배터리 체크 주기: {CONVOY_BATTERY_CHECK_INTERVAL // 60}분")
    log_activity("convoy", "convoy_start",
                 f"Convoy 대열 작업 시작 (로봇: {', '.join(robot_names)})",
                 source="start_convoy")

    # 대기 풀에서 W에 있는 로봇들을 빈 충전소로 이동 (1회, 60초 지연)
    threading.Thread(
        target=_move_standby_pool_to_charging,
        args=(60.0,),
        daemon=True,
        name="standby-to-charging",
    ).start()
    return True, "Convoy 대열 작업이 시작되었습니다"


def _move_standby_pool_to_charging(delay_sec: float = 60.0):
    """Convoy 시작 직후, 대기 풀에서 W(대기장소)에 있는 로봇들을 빈 충전소로 이동.
    - 첫 시도: delay_sec(60초) 후
    - 실패(빈 충전소 없음 등) 로봇이 남아있으면 5분 후 재시도
    - pool에 W 로봇 없거나 convoy 중단되면 종료
    """
    stop_event = _convoy_stop_event
    if stop_event is None:
        return

    RETRY_INTERVAL = 300.0  # 재시도 간격: 5분
    wait_sec = delay_sec

    while True:
        # 지연 대기 — convoy가 중단되면 종료
        if stop_event.wait(timeout=wait_sec):
            return

        with _convoy_lock:
            pool_snapshot = list(_convoy_standby_pool)
            cur_map_id = _convoy_map_id

        # 더 이상 pool에 W 로봇 없으면 종료
        w_remaining = [
            r for r in pool_snapshot
            if ((r.get("_start_poi_name") or r.get("standby_poi_name") or "").startswith("W"))
        ]
        if not w_remaining:
            logger.info("[Standby→C] W에 남은 대기 로봇 없음 — 종료")
            return
        if not cur_map_id:
            logger.info("[Standby→C] 맵 미확정 — 재시도 대기")
            wait_sec = RETRY_INTERVAL
            continue

        logger.info(f"[Standby→C] 체크 시작 — W 대기 로봇 {len(w_remaining)}대")

        for rc in w_remaining:
            if stop_event.is_set():
                return

            robot_id = rc["robot_id"]
            robot_ip = rc["ip"]
            start_poi = rc.get("_start_poi_name") or rc.get("standby_poi_name")

            db = SessionLocal()
            ws = None
            try:
                # convoy 중인 로봇은 물리적으로 출발지에 없으므로 점유 제외
                with _convoy_lock:
                    convoy_rids = {r["robot_id"] for r in _convoy_robots}

                occupied_ids = set()
                for r in db.query(Robot).filter(
                    Robot.is_active == True, Robot.id != robot_id
                ).all():
                    if r.id in convoy_rids:
                        continue  # convoy 중 — 원래 C에서 나감
                    if r.charging_id:
                        occupied_ids.add(r.charging_id)

                free_c = None
                for cname in ["C1", "C2", "C3"]:
                    cpoi = db.query(MapPOI).filter(
                        MapPOI.name == cname, MapPOI.is_active == True,
                        MapPOI.map_id == cur_map_id,
                    ).first()
                    if cpoi and cpoi.id not in occupied_ids:
                        free_c = cpoi
                        break

                if not free_c:
                    logger.info(f"[Standby→C] 로봇 {robot_id} ({start_poi}): 빈 충전소 없음 — 대기 유지")
                    continue

                c_name = free_c.name
                tx = free_c.world_x if free_c.world_x is not None else free_c.x
                ty = free_c.world_y if free_c.world_y is not None else free_c.y
                t_angle = free_c.angle if free_c.angle is not None else 0.0

                logger.info(f"[Standby→C] 로봇 {robot_id} ({start_poi}) → {c_name} 이동 시작")

                move_lock = _get_move_lock(robot_id)
                try:
                    ws = _create_planning_ws(robot_ip)
                except Exception:
                    ws = None

                ws, result, _ = _execute_move(
                    robot_id, robot_ip, float(tx), float(ty), float(t_angle), "",
                    ws, move_lock, stop_event, max_retries=2,
                )

                if result != "succeeded":
                    logger.warning(f"[Standby→C] 로봇 {robot_id} → {c_name} 이동 실패 ({result}) — 대기 유지")
                    continue

                # 도킹
                time.sleep(1.0)
                send_charge(robot_ip, charger_name=c_name)
                _update_robot_status(robot_id, "charging", message="충전 중")

                # DB 업데이트: standby_id → None, charging_id → 빈 충전소
                robot_row = db.query(Robot).filter(Robot.id == robot_id).first()
                if robot_row:
                    robot_row.standby_id = None
                    robot_row.charging_id = free_c.id
                    db.commit()

                # pool 엔트리 업데이트 (hot-swap 시 올바른 경로 사용)
                with _convoy_lock:
                    for pool_rc in _convoy_standby_pool:
                        if pool_rc["robot_id"] == robot_id:
                            pool_rc["entry_poi_names"] = [f"{c_name}-1", "ENTER-LAST"]
                            pool_rc["return_poi_names"] = ["ENTER-LAST", f"{c_name}-1"]
                            pool_rc["charging_poi_name"] = c_name
                            pool_rc["standby_poi_name"] = None
                            pool_rc["start_poi_type"] = "charging"
                            pool_rc["_start_poi_name"] = c_name
                            break

                logger.info(f"[Standby→C] 로봇 {robot_id} → {c_name} 도킹 완료 (충전 시작)")
                _rname = rc.get("robot_name") or f"로봇 {robot_id}"
                log_activity("robot", "standby_charge",
                             f"대기 로봇 {_rname} → {c_name} 충전 이동",
                             robot_id=robot_id, robot_name=_rname,
                             source="_move_standby_pool_to_charging")
            except Exception as e:
                logger.exception(f"[Standby→C] 로봇 {robot_id} 이동 예외: {e}")
            finally:
                if ws:
                    try:
                        ws.close()
                    except Exception:
                        pass
                db.close()

        # 한 iteration 끝 — 다음 재시도 대기
        wait_sec = RETRY_INTERVAL


def start_convoy_resume(
    robots_config: list[dict],
    work_poi_names: list[str],
    stop_names: list[str],
    standby_robots: list[dict] | None = None,
) -> tuple[bool, str]:
    """Convoy 재개 모드 — 저장된 WORK 노드 위치에서 작업 재개

    robots_config 각 항목에 resume_node_index가 포함되어 있으면
    해당 노드로 직접 이동 후 작업 루프 재개.
    먼 노드(node_index 큰 순) 로봇부터 순차 출발.
    """
    global _convoy_phase, _convoy_stop_event, _convoy_graceful_event
    global _convoy_robots, _convoy_robot_status, _convoy_node_positions
    global _convoy_standby_pool, _convoy_work_poi_names, _convoy_stop_names
    global _convoy_hotswap_threads, _convoy_map_id, _convoy_return_events
    global _convoy_is_resume

    with _convoy_lock:
        if _convoy_phase not in ("idle", "stopped", "error"):
            return False, f"이미 convoy 실행 중입니다 (phase={_convoy_phase})"

        _convoy_phase = "entering"
        _convoy_is_resume = True
        _convoy_stop_event = threading.Event()
        _convoy_graceful_event = threading.Event()
        _convoy_robots = robots_config[:]
        _convoy_robot_status = {rc["robot_id"]: {"status": "waiting"} for rc in robots_config}
        _convoy_node_positions.clear()
        _convoy_reassign_done.clear()
        _fire_event.clear()
        _convoy_standby_pool = list(standby_robots) if standby_robots else []
        _convoy_work_poi_names = work_poi_names[:]
        _convoy_stop_names = stop_names[:]
        _convoy_return_requested.clear()
        _convoy_hotswap_threads.clear()
        _convoy_map_id = None
        _convoy_return_events = {rc["robot_id"]: threading.Event() for rc in robots_config}
        _convoy_all_arrived.clear()

    # 재개 오케스트레이터 스레드 시작
    t = threading.Thread(
        target=_convoy_orchestrator_resume,
        args=(robots_config, work_poi_names, stop_names),
        daemon=True,
        name="convoy-orchestrator-resume",
    )
    t.start()
    _start_convoy_flush()

    robot_ids = [rc['robot_id'] for rc in robots_config]
    resume_info = {rc['robot_id']: rc.get('resume_node_index', '?') for rc in robots_config}
    logger.info(f"[Convoy] 재개 모드 시작 — 로봇: {robot_ids}, 노드: {resume_info}")
    log_activity("convoy", "convoy_resume",
                 f"Convoy 재개 시작 (저장 위치에서 작업 재개)",
                 source="start_convoy_resume")

    # 대기 풀에서 W에 있는 로봇들을 빈 충전소로 이동 (1회, 60초 지연)
    threading.Thread(
        target=_move_standby_pool_to_charging,
        args=(60.0,),
        daemon=True,
        name="standby-to-charging",
    ).start()
    return True, "Convoy 재개 — 저장된 위치에서 작업을 재개합니다"


# ─── Convoy 정지 ───────────────────────────────────────────────────────────────

def _get_robot_pose(robot_ip: str) -> tuple[float, float, float] | None:
    """로봇 실제 좌표(x, y, orientation) 조회"""
    try:
        ws = _create_planning_ws(robot_ip)
        import json as _json
        ws.send(_json.dumps({"enable_topic": "/tracked_pose"}))
        deadline = time.time() + 3.0
        while time.time() < deadline:
            raw = ws.recv()
            if not raw:
                continue
            pkt = _json.loads(raw)
            if pkt.get("topic") == "/tracked_pose":
                pos = pkt.get("pos", [])
                ori = pkt.get("ori", 0.0)
                if len(pos) >= 2:
                    ws.close()
                    return float(pos[0]), float(pos[1]), float(ori)
        ws.close()
    except Exception as e:
        logger.warning(f"[Convoy/{robot_ip}] pose 조회 실패: {e}")
    return None


def _update_saved_position(robot_id: int, robot_ip: str):
    """개별 로봇의 저장 상태에 실제 좌표만 갱신 (node_index는 유지)"""
    pose = _get_robot_pose(robot_ip)
    if not pose:
        logger.warning(f"[Convoy] 로봇 {robot_id} 실좌표 조회 실패 — 갱신 생략")
        return

    actual_x, actual_y, actual_ori = pose

    db = SessionLocal()
    try:
        row = db.query(ConvoySavedState).filter(
            ConvoySavedState.robot_id == robot_id
        ).first()
        if row:
            row.actual_x = actual_x
            row.actual_y = actual_y
            row.actual_ori = actual_ori
            db.commit()
            logger.info(f"[Convoy] 로봇 {robot_id} 실좌표 갱신 → "
                        f"({actual_x:.3f}, {actual_y:.3f}, ori={actual_ori:.3f}), "
                        f"node 유지={row.work_poi_name}(idx={row.node_index})")
        else:
            logger.warning(f"[Convoy] 로봇 {robot_id} 저장 상태 없음 — 갱신 생략")
    except Exception as e:
        db.rollback()
        logger.error(f"[Convoy] 로봇 {robot_id} 좌표 갱신 실패: {e}")
    finally:
        db.close()


def _save_convoy_positions():
    """전체 삭제 → 현재 활성 로봇만 새로 저장 (실좌표 포함)
    배터리 교체로 로봇이 바뀌어도 항상 현재 활성 로봇만 남음
    """
    db = SessionLocal()
    try:
        db.query(ConvoySavedState).delete()

        # 노드에 있는 로봇만 수집 (node_positions에 값이 있는 로봇)
        active_robots = {}  # {robot_id: ip}
        for rid, node_idx in _convoy_node_positions.items():
            if node_idx is not None:
                for rc in _convoy_robots:
                    if rc["robot_id"] == rid:
                        active_robots[rid] = rc["ip"]
                        break

        logger.info(f"[Convoy] 위치 저장 — 활성 로봇={list(active_robots.keys())}, "
                    f"positions={dict(_convoy_node_positions)}")

        if not active_robots:
            logger.warning("[Convoy] 저장할 로봇 없음!")
            db.commit()
            return

        for rid, ip in active_robots.items():
            node_idx = _convoy_node_positions.get(rid)
            if node_idx is None:
                node_idx = 0
            poi_name = _convoy_work_poi_names[node_idx] if node_idx < len(_convoy_work_poi_names) else "WORK1"

            # 실좌표는 워커에서 멈춘 후 _update_saved_position으로 갱신
            db.add(ConvoySavedState(
                robot_id=rid,
                node_index=node_idx,
                work_poi_name=poi_name or "WORK1",
            ))

        db.commit()
        logger.info(f"[Convoy] 위치 저장 완료: {len(active_robots)}대")
    except Exception as e:
        db.rollback()
        logger.error(f"[Convoy] 로봇 위치 저장 실패: {e}")
    finally:
        db.close()


def _sequential_return_trigger(positions_snapshot: list[tuple[int, int]]):
    """먼 로봇(node_index 큰 순)부터 3초 대기 후 7초 간격으로 개별 복귀 이벤트 발행

    positions_snapshot: [(robot_id, node_index), ...] — stop 시점의 스냅샷
    """
    time.sleep(15.0)  # 초기 15초 대기

    # 먼 노드부터 정렬
    positions_snapshot.sort(key=lambda x: x[1], reverse=True)

    logger.info(f"[Convoy] 순차 복귀 시작 — 순서: {positions_snapshot}")

    for i, (rid, node_idx) in enumerate(positions_snapshot):
        if _convoy_stop_event and _convoy_stop_event.is_set():
            break
        ev = _convoy_return_events.get(rid)
        if ev:
            logger.info(f"[Convoy] 순차 복귀 #{i+1} — 로봇 {rid} (node={node_idx}) 복귀 신호")
            ev.set()
        else:
            logger.warning(f"[Convoy] 로봇 {rid} 복귀 이벤트 없음")
        if i < len(positions_snapshot) - 1:
            for _ in range(15):
                if _convoy_stop_event and _convoy_stop_event.is_set():
                    break
                time.sleep(1.0)


def stop_convoy() -> tuple[bool, str]:
    """즉시 정지 + 순차 복귀 — 모든 로봇 이동 즉시 취소 → 먼 로봇부터 3초 대기 → 7초 간격 복귀"""
    global _convoy_phase, _convoy_hourly_timer

    with _convoy_lock:
        if _convoy_phase in ("idle", "stopped"):
            return False, "실행 중인 convoy가 없습니다"

        # 정지 전 현재 위치 저장 (재시작 시 활용)
        _save_convoy_positions()

        robots = _convoy_robots[:]
        # 노드 위치 스냅샷 (워커가 지우기 전에 캡처, None은 0으로)
        all_robot_ids = {rc["robot_id"] for rc in robots}
        all_robot_ids.update(_convoy_node_positions.keys())
        positions_snapshot = [(rid, _convoy_node_positions.get(rid) or 0) for rid in all_robot_ids]
        cur_map_id = _convoy_map_id

    # 배터리 기준 복귀 위치 재배치 — 배터리 낮은 로봇부터 C1→C2→C3 우선
    # (재배치가 DB를 업데이트하므로 graceful_event 세팅 전에 수행)
    try:
        with _convoy_hot_swap_lock:
            _reassign_convoy_positions(map_id=cur_map_id)
    except Exception as e:
        logger.warning(f"[Convoy] 정지 전 배터리 재배치 실패: {e}")

    with _convoy_lock:
        if _convoy_graceful_event:
            _convoy_graceful_event.set()
        _convoy_phase = "returning"

    # 종료 시 배터리 체크 타이머 취소
    if _convoy_hourly_timer:
        _convoy_hourly_timer.cancel()
        _convoy_hourly_timer = None

    # 모든 로봇 이동 즉시 취소 (병렬)
    def _cancel_robot(rc):
        try:
            cancel_and_verify(rc["ip"])
            logger.info(f"[Convoy] 로봇 {rc['robot_id']} 이동 취소 완료")
        except Exception as e:
            logger.warning(f"[Convoy] 로봇 {rc['robot_id']} 이동 취소 실패: {e}")

    cancel_threads = []
    for rc in robots:
        ct = threading.Thread(target=_cancel_robot, args=(rc,), daemon=True)
        ct.start()
        cancel_threads.append(ct)
    for ct in cancel_threads:
        ct.join(timeout=6.0)

    # 순차 복귀 스레드 시작 (3초 후 먼 로봇부터 7초 간격)
    t = threading.Thread(target=_sequential_return_trigger, args=(positions_snapshot,),
                         daemon=True, name="convoy-sequential-return")
    t.start()

    logger.info("[Convoy] 즉시 정지 + 순차 복귀 요청")
    log_activity("convoy", "convoy_stop_request",
                 "Convoy 즉시 정지 — 순차 복귀 시작",
                 source="stop_convoy")
    return True, "Convoy 즉시 정지 — 먼 로봇부터 순차 복귀합니다."


def force_stop_convoy() -> tuple[bool, str]:
    """즉시 정지 — 모든 로봇 이동 취소 + 상태 리셋"""
    global _convoy_phase

    # 타이머 취소
    global _convoy_hourly_timer
    if _convoy_hourly_timer:
        _convoy_hourly_timer.cancel()
        _convoy_hourly_timer = None

    with _convoy_lock:
        robots = _convoy_robots[:]
        node_positions_snapshot = dict(_convoy_node_positions)
        work_names = list(_convoy_work_poi_names)
        # stop_event만 세팅 → 모든 워커 스레드 즉시 탈출 (graceful 세팅 금지 — 복귀 방지)
        if _convoy_stop_event:
            _convoy_stop_event.set()
        _convoy_phase = "stopped"
        _convoy_robot_status.clear()
        _convoy_node_positions.clear()
        _convoy_battery_cache.clear()
        _fire_event.clear()  # 화재 이벤트 초기화

    # 태블릿 상태 정리 (즉시)
    with _task_lock:
        for rc in robots:
            _confirm_events.pop(rc["robot_id"], None)
            _run_info.pop(rc["robot_id"], None)
            _stuck_states.pop(rc["robot_id"], None)

    # 모든 로봇의 현재 이동 취소 — 백그라운드 병렬 실행 (API 블로킹 방지)
    def _cancel_robot(rc):
        try:
            cancel_and_verify(rc["ip"])
            logger.info(f"[Convoy] 로봇 {rc['robot_id']} 이동 취소 완료")
        except Exception as e:
            logger.warning(f"[Convoy] 로봇 {rc['robot_id']} 이동 취소 실패: {e}")

    cancel_threads = []
    for rc in robots:
        t = threading.Thread(target=_cancel_robot, args=(rc,), daemon=True)
        t.start()
        cancel_threads.append(t)

    # 최대 6초 대기 (타임아웃 — API 응답 지연 방지)
    for t in cancel_threads:
        t.join(timeout=6.0)

    # 로봇 현재 위치를 DB에 저장 (다시 출발용)
    try:
        _db = SessionLocal()
        _db.query(ConvoySavedState).delete()
        for rc in robots:
            rid = rc["robot_id"]
            pose = _get_robot_pose(rc["ip"])
            node_idx = node_positions_snapshot.get(rid, 0)
            work_name = work_names[node_idx] if work_names and node_idx < len(work_names) else "WORK1"
            if pose:
                _db.add(ConvoySavedState(
                    robot_id=rid,
                    node_index=node_idx,
                    work_poi_name=work_name,
                    actual_x=pose[0],
                    actual_y=pose[1],
                    actual_ori=pose[2],
                ))
        _db.commit()
        logger.info(f"[Convoy] 비상정지 — {len(robots)}대 위치 저장 완료")
    except Exception as e:
        logger.warning(f"[Convoy] 비상정지 위치 저장 실패: {e}")
    finally:
        _db.close()

    _stop_convoy_flush()
    logger.warning("[Convoy] 즉시 정지 완료 — 모든 이동 취소됨")
    log_activity("convoy", "convoy_force_stop",
                 "Convoy 즉시 정지 — 모든 로봇 이동 취소",
                 source="force_stop_convoy")
    return True, "Convoy 즉시 정지 — 모든 로봇 이동 취소됨"


# ─── Hot Swap: 대기 로봇 투입 ──────────────────────────────────────────────────

def _trigger_standby_robot() -> bool:
    """대기 풀에서 로봇 꺼내 convoy에 즉시 투입 (배터리 부족 hot swap).
    배터리가 가장 높은 로봇을 우선 선택 — 조회 실패 로봇은 맨 뒤로.
    반환: True=투입 성공, False=대기 로봇 없음
    """
    # 락 밖에서 후보 배터리 조회 (WS/HTTP 호출 블로킹 방지)
    with _convoy_lock:
        candidates = list(_convoy_standby_pool)
    if not candidates:
        logger.warning("[Convoy] 대기 로봇 없음 — hot swap 불가")
        return False

    scored: list[tuple[int, float, dict]] = []  # (robot_id, pct, rc)
    for c_rc in candidates:
        pct = _get_battery_percentage(c_rc["ip"])
        scored.append((c_rc["robot_id"], pct if pct is not None else -1.0, c_rc))
    # 배터리 내림차순, 조회 실패(-1)는 맨 뒤
    scored.sort(key=lambda x: x[1], reverse=True)
    best_rid, best_pct, best_rc = scored[0]

    with _convoy_lock:
        # race: pool에서 해당 로봇이 빠졌을 수 있으니 재확인
        try:
            _convoy_standby_pool.remove(best_rc)
        except ValueError:
            # 이미 빠졌으면 현재 pool의 첫 번째로 폴백
            if not _convoy_standby_pool:
                logger.warning("[Convoy] 대기 로봇 없음 — hot swap 불가")
                return False
            best_rc = _convoy_standby_pool.pop(0)
            best_rid = best_rc["robot_id"]
            best_pct = -1.0
        rc = best_rc
        _convoy_robots.append(rc)
        _convoy_robot_status[rc["robot_id"]] = {"status": "waiting"}
        stop_event = _convoy_stop_event
        graceful_event = _convoy_graceful_event

    logger.info(
        f"[Convoy Hot Swap] 대기 로봇 {best_rid} 선택 (배터리 {best_pct:.1f}%) — "
        f"후보 {len(scored)}대 중 최고 배터리"
    )

    logger.info(f"[Convoy Hot Swap] 대기 로봇 {rc['robot_id']} 투입 시작 "
                f"— 진입경로: {rc.get('entry_poi_names')}, "
                f"stop={stop_event.is_set() if stop_event else 'None'}, "
                f"graceful={graceful_event.is_set() if graceful_event else 'None'}")

    if stop_event and stop_event.is_set():
        logger.error(f"[Convoy Hot Swap] stop_event 이미 set — 로봇 {rc['robot_id']} 투입 취소")
        return False

    arrival_ev = threading.Event()
    return_ready_ev = threading.Event()

    t = threading.Thread(
        target=_convoy_robot_worker,
        args=(
            rc, _convoy_work_poi_names, _convoy_stop_names,
            stop_event, graceful_event,
            None, arrival_ev, return_ready_ev,
        ),
        daemon=True,
        name=f"convoy-robot-hotswap-{rc['robot_id']}",
    )
    t.start()
    with _convoy_lock:
        _convoy_hotswap_threads.append(t)
        # hot swap 로봇도 복귀 이벤트 등록 (정지 시 순차 복귀 가능하도록)
        if rc["robot_id"] not in _convoy_return_events:
            _convoy_return_events[rc["robot_id"]] = threading.Event()
    logger.info(f"[Convoy Hot Swap] 로봇 {rc['robot_id']} 워커 스레드 시작 완료")
    _hs_name = rc.get("robot_name") or f"로봇 {rc['robot_id']}"
    log_activity("robot", "hot_swap_deploy",
                 f"Convoy Hot Swap — {_hs_name} 투입",
                 robot_id=rc["robot_id"], robot_name=_hs_name, source="_trigger_standby_robot")
    return True


def _schedule_requeue(robot_id: int, robot_ip: str, requeue_rc: dict):
    """배터리 부족으로 복귀한 로봇을 standby pool에 즉시 재등록.
    convoy가 여전히 running 상태일 때만 등록 (중복 방지 포함).
    """
    with _convoy_lock:
        if _convoy_phase != "running":
            logger.info(f"[Robot {robot_id}] convoy 미실행 — requeue 취소")
            return
        already = any(r["robot_id"] == robot_id for r in _convoy_standby_pool)
        if already:
            logger.info(f"[Robot {robot_id}] 이미 standby pool에 등록됨 — 중복 방지")
            return
        _convoy_standby_pool.append(requeue_rc)



# ─── 오케스트레이터 (순차 출발 제어) ───────────────────────────────────────────

def _convoy_orchestrator(
    robots_config: list[dict],
    work_poi_names: list[str],
    stop_names: list[str],
):
    """메인 오케스트레이터 스레드
    1. C1 워커 시작 → WORK1 도착 대기
    2. C2 워커 시작 → WORK1 도착 대기
    3. C3 워커 시작
    4. 모든 워커 종료 대기
    """
    global _convoy_phase

    stop_event = _convoy_stop_event
    graceful_event = _convoy_graceful_event

    # 로봇별 이벤트
    arrival_events: list[threading.Event] = []
    worker_threads: list[threading.Thread] = []

    # 복귀 완료 이벤트 (C3→C2→C1 순서 제어용)
    return_ready_events: list[threading.Event] = []

    try:
        for i, rc in enumerate(robots_config):
            arrival_ev = threading.Event()
            return_ready_ev = threading.Event()
            arrival_events.append(arrival_ev)
            return_ready_events.append(return_ready_ev)

            wait_event = None
            t = threading.Thread(
                target=_convoy_robot_worker,
                args=(
                    rc, work_poi_names, stop_names,
                    stop_event, graceful_event,
                    wait_event, arrival_ev,
                    return_ready_ev,
                ),
                daemon=True,
                name=f"convoy-robot-{rc['robot_id']}",
            )
            worker_threads.append(t)

        # 순차적으로 시작: 7초 간격으로 출발
        INTER_ROBOT_DELAY = 15

        for i, (t, rc) in enumerate(zip(worker_threads, robots_config)):
            if stop_event.is_set():
                break

            _rname = rc.get('robot_name') or f"로봇 {rc['robot_id']}"
            log_activity("robot", "convoy_robot_depart",
                         f"Convoy 로봇 '{_rname}' 출발 (#{i+1})",
                         robot_id=rc['robot_id'], robot_name=_rname, source="_convoy_orchestrator")
            t.start()

            if i < len(robots_config) - 1:
                for _ in range(INTER_ROBOT_DELAY):
                    if stop_event.is_set():
                        break
                    time.sleep(1.0)

                if stop_event.is_set():
                    break

        # 뒤 로봇의 return_ready_event 연결 (워커 스레드 시작 후)
        # 복귀 순서: C3(idx=2) → C2(idx=1) → C1(idx=0)
        # C3: wait_return = None (즉시 복귀)
        # C2: wait_return = return_ready_events[2] (C3 복귀 완료 대기)
        # C1: wait_return = return_ready_events[1] (C2 복귀 완료 대기)
        # → 워커에 wait_return_event를 직접 전달하지 않고, 별도로 관리

        with _convoy_lock:
            if _convoy_phase == "entering":
                _convoy_phase = "running"
                log_activity("convoy", "convoy_phase_running",
                             "Convoy 전체 진입 완료 — 순환 작업 시작",
                             source="_convoy_orchestrator")

        # 1시간 배터리 체크 타이머 시작
        _schedule_hourly_check(stop_event)

        # 모든 워커 종료 대기 (원래 워커)
        for t in worker_threads:
            t.join()

        # hot swap 워커도 모두 대기 (동적으로 추가될 수 있으므로 루프 처리)
        joined_hs: set[int] = set()
        while True:
            with _convoy_lock:
                pending = [t for t in _convoy_hotswap_threads if id(t) not in joined_hs]
            if not pending:
                break
            for t in pending:
                t.join()
                joined_hs.add(id(t))

        # 타이머 취소 (워커 모두 종료)
        global _convoy_hourly_timer
        if _convoy_hourly_timer:
            _convoy_hourly_timer.cancel()
            _convoy_hourly_timer = None

        log_activity("convoy", "convoy_complete",
                     "Convoy 모든 로봇 작업 종료",
                     source="_convoy_orchestrator")

        with _convoy_lock:
            _convoy_phase = "stopped"
        _stop_convoy_flush()

    except Exception as e:
        logger.exception(f"[Convoy] 오케스트레이터 예외: {e}")
        if _convoy_hourly_timer:
            _convoy_hourly_timer.cancel()
            _convoy_hourly_timer = None
        with _convoy_lock:
            _convoy_phase = "error"
        _stop_convoy_flush()


# ─── 재개 모드 오케스트레이터 ──────────────────────────────────────────────────

def _convoy_orchestrator_resume(
    robots_config: list[dict],
    work_poi_names: list[str],
    stop_names: list[str],
):
    """재개 모드 오케스트레이터
    - 로봇은 이미 먼 노드 순으로 정렬되어 있음 (라우터에서)
    - 각 로봇이 저장된 WORK 노드로 진입 후 작업 루프 재개
    - 7초 간격 순차 출발 유지
    """
    global _convoy_phase

    stop_event = _convoy_stop_event
    graceful_event = _convoy_graceful_event

    arrival_events: list[threading.Event] = []
    worker_threads: list[threading.Thread] = []
    return_ready_events: list[threading.Event] = []

    try:
        for i, rc in enumerate(robots_config):
            arrival_ev = threading.Event()
            return_ready_ev = threading.Event()
            arrival_events.append(arrival_ev)
            return_ready_events.append(return_ready_ev)

            wait_event = None
            t = threading.Thread(
                target=_convoy_robot_worker,
                args=(
                    rc, work_poi_names, stop_names,
                    stop_event, graceful_event,
                    wait_event, arrival_ev,
                    return_ready_ev,
                ),
                daemon=True,
                name=f"convoy-robot-resume-{rc['robot_id']}",
            )
            worker_threads.append(t)

        # 순차적으로 시작: 먼 노드부터 10초 간격으로 출발
        for i, (t, rc) in enumerate(zip(worker_threads, robots_config)):
            if stop_event.is_set():
                break

            resume_poi = rc.get("resume_work_poi_name", "?")
            _rname = rc.get('robot_name') or f"로봇 {rc['robot_id']}"
            log_activity("robot", "convoy_robot_resume_depart",
                         f"Convoy 재개 — '{_rname}' → {resume_poi} 출발 (#{i+1})",
                         robot_id=rc['robot_id'], robot_name=_rname,
                         source="_convoy_orchestrator_resume")
            logger.info(f"[Convoy] 재개 #{i+1} — {_rname} → {resume_poi} 출발")
            t.start()

            # 15초 대기 후 다음 로봇 출발
            if i < len(robots_config) - 1:
                for _ in range(15):
                    if stop_event.is_set():
                        break
                    time.sleep(1.0)
                if stop_event.is_set():
                    break

        # 마지막 로봇 도착 대기
        if arrival_events and not stop_event.is_set():
            arrival_events[-1].wait()

        if not stop_event.is_set():
            global _convoy_countdown_until
            logger.info("[Convoy] 재개 모드 — 전원 도착 완료, 5초 대기 후 작업 시작")
            _update_all_status_message("전원 도착 — 5초 후 작업 시작")
            _convoy_countdown_until = time.time() + 5.0
            for _ in range(5):
                if stop_event.is_set():
                    break
                time.sleep(1.0)
            _convoy_countdown_until = None

        # 전원 도착 + 딜레이 완료 → 작업 루프 시작 신호
        _convoy_all_arrived.set()

        with _convoy_lock:
            if _convoy_phase == "entering":
                _convoy_phase = "running"
                log_activity("convoy", "convoy_phase_running",
                             "Convoy 재개 진입 완료 — 순환 작업 시작",
                             source="_convoy_orchestrator_resume")

        # 배터리 체크 타이머 시작
        _schedule_hourly_check(stop_event)

        # 모든 워커 종료 대기
        for t in worker_threads:
            t.join()

        # hot swap 워커도 대기
        joined_hs: set[int] = set()
        while True:
            with _convoy_lock:
                pending = [t for t in _convoy_hotswap_threads if id(t) not in joined_hs]
            if not pending:
                break
            for t in pending:
                t.join()
                joined_hs.add(id(t))

        global _convoy_hourly_timer
        if _convoy_hourly_timer:
            _convoy_hourly_timer.cancel()
            _convoy_hourly_timer = None

        log_activity("convoy", "convoy_complete",
                     "Convoy 모든 로봇 작업 종료 (재개 모드)",
                     source="_convoy_orchestrator_resume")

        with _convoy_lock:
            _convoy_phase = "stopped"
        _stop_convoy_flush()

    except Exception as e:
        logger.exception(f"[Convoy] 재개 오케스트레이터 예외: {e}")
        if _convoy_hourly_timer:
            _convoy_hourly_timer.cancel()
            _convoy_hourly_timer = None
        with _convoy_lock:
            _convoy_phase = "error"
        _stop_convoy_flush()


# ─── 시간 기반 배터리 체크 ────────────────────────────────────────────────────────

def _convoy_hourly_battery_check(stop_event: threading.Event):
    """1시간마다 convoy 로봇 배터리 조회 → 최저 배터리 로봇 복귀 요청"""
    global _convoy_return_requested

    if stop_event.is_set():
        return

    with _convoy_lock:
        if _convoy_phase != "running":
            return
        robots = _convoy_robots[:]

    if not robots:
        _schedule_hourly_check(stop_event)
        return

    # 대기 로봇이 없으면 스킵 (교체할 로봇이 없으므로 배터리 스케줄링 불필요)
    with _convoy_lock:
        standby_count = len(_convoy_standby_pool)
    if standby_count == 0:
        logger.info("[Convoy 시간 체크] 대기 로봇 없음 — 배터리 교체 스킵")
        _schedule_hourly_check(stop_event)
        return

    # 배터리 조회 — 진입 중(entering/waiting) 로봇은 제외
    battery_levels = []
    for rc in robots:
        rid = rc["robot_id"]
        with _convoy_lock:
            rs = _convoy_robot_status.get(rid, {})
        if rs.get("status") in ("entering", "waiting"):
            continue
        pct = _get_battery_percentage(rc["ip"])
        battery_levels.append((rid, pct if pct is not None else 100.0))

    if not battery_levels:
        _schedule_hourly_check(stop_event)
        return

    # 최저 배터리 로봇 선택
    battery_levels.sort(key=lambda x: x[1])
    min_robot_id, min_pct = battery_levels[0]
    logger.info(f"[Convoy 시간 체크] 최저 배터리 로봇 {min_robot_id} ({min_pct:.1f}%)")

    # 대기 풀 로봇 배터리 최고값 조회 — 교체 가치 판단
    with _convoy_lock:
        pool_snapshot = list(_convoy_standby_pool)

    pool_best_pct = -1.0
    pool_best_rid = None
    for rc in pool_snapshot:
        pct = _get_battery_percentage(rc["ip"])
        if pct is None:
            continue
        if pct > pool_best_pct:
            pool_best_pct = pct
            pool_best_rid = rc["robot_id"]

    # 대기 풀 최고 배터리 <= convoy 최저 배터리 → 교체 스킵
    # (최소 5% 마진 — 근소한 차이로는 이동 비용 대비 이득 없음)
    BATTERY_SWAP_MARGIN = 5.0
    if pool_best_pct <= min_pct + BATTERY_SWAP_MARGIN:
        logger.info(
            f"[Convoy 시간 체크] 스킵 — 대기 풀 최고({pool_best_rid}:{pool_best_pct:.1f}%) "
            f"<= convoy 최저({min_robot_id}:{min_pct:.1f}%) + 마진 {BATTERY_SWAP_MARGIN}%"
        )
        _schedule_hourly_check(stop_event)
        return

    logger.info(
        f"[Convoy 시간 체크] 교체 진행 — 대기 풀 최고({pool_best_rid}:{pool_best_pct:.1f}%) "
        f"> convoy 최저({min_robot_id}:{min_pct:.1f}%) + 마진"
    )

    # 복귀 요청 등록
    with _convoy_lock:
        _convoy_return_requested.add(min_robot_id)

    # 복귀 로봇에게 충전소 먼저 예약 (C1 우선)
    _reserved_charging = None
    try:
        _db = SessionLocal()
        occupied_poi_ids = set()
        for r in _db.query(Robot).filter(Robot.is_active == True, Robot.id != min_robot_id).all():
            if r.charging_id:
                occupied_poi_ids.add(r.charging_id)
        cur_map_id = _convoy_map_id
        if cur_map_id:
            for cname in ["C1", "C2", "C3"]:
                cpoi = _db.query(MapPOI).filter(
                    MapPOI.name == cname, MapPOI.is_active == True,
                    MapPOI.map_id == cur_map_id,
                ).first()
                if cpoi and cpoi.id not in occupied_poi_ids:
                    # 복귀 로봇에게 충전소 배정
                    robot_row = _db.query(Robot).filter(Robot.id == min_robot_id).first()
                    if robot_row:
                        robot_row.charging_id = cpoi.id
                        robot_row.standby_id = None
                        _db.commit()
                        _reserved_charging = cname
                        logger.info(f"[Convoy 시간 체크] 복귀 로봇 {min_robot_id} → {cname} 예약")
                    break
        _db.close()
    except Exception as e:
        logger.warning(f"[Convoy 시간 체크] 충전소 예약 실패: {e}")

    # 배터리 기반 위치 재배치 (복귀 로봇 충전소 제외)
    with _convoy_hot_swap_lock:
        with _convoy_lock:
            cur_map_id = _convoy_map_id
        excluded = {_reserved_charging} if _reserved_charging else set()
        _reassign_convoy_positions(map_id=cur_map_id, excluded_positions=excluded)

    # 재배치 완료 후 convoy에서 제거
    with _convoy_lock:
        orig_len = len(_convoy_robots)
        _convoy_robots[:] = [r for r in _convoy_robots if r["robot_id"] != min_robot_id]
        was_removed = len(_convoy_robots) < orig_len

    if not was_removed:
        logger.info(f"[Convoy 시간 체크] 로봇 {min_robot_id} 이미 convoy에서 제거됨")
    # 대기 로봇 투입은 복귀 로봇이 충전소에 실제 도착 후 워크루프에서 수행

    # 다음 1시간 타이머 예약
    _schedule_hourly_check(stop_event)


def _schedule_hourly_check(stop_event: threading.Event):
    """1시간 후 배터리 체크 타이머 예약"""
    global _convoy_hourly_timer

    if stop_event.is_set():
        return

    t = threading.Timer(
        CONVOY_BATTERY_CHECK_INTERVAL,
        _convoy_hourly_battery_check,
        args=(stop_event,),
    )
    t.daemon = True
    _convoy_hourly_timer = t
    t.start()
    logger.info(f"[Convoy] 다음 배터리 체크: {CONVOY_BATTERY_CHECK_INTERVAL // 60}분 후")


# ─── 배터리 로테이션 (대기 상태 시) ──────────────────────────────────────────

BATTERY_ROTATION_INTERVAL = 180  # 3분 간격


def _battery_rotation_check():
    """작업 대기 상태일 때 충전 로봇 ↔ 대기 로봇 자동 로테이션

    - C1/C2/C3 로봇 중 배터리가 max_battery 이상이고
    - W1/W2에 대기 로봇이 있으면
    - 오래 충전된 순서로 W1/W2 로봇과 위치 교체
    """
    try:
        if _battery_rotation_stop.is_set():
            return

        # convoy 실행 중이면 스킵
        with _convoy_lock:
            if _convoy_phase not in ("idle", "stopped"):
                _schedule_battery_rotation()
                return

        db = SessionLocal()
        try:
            # 활성 로봇 전체 조회
            active_robots = db.query(Robot).filter(
                Robot.is_active == True,
                Robot.ip_address.isnot(None),
            ).all()

            # POI 위치별 로봇 매핑
            charging_robots = []   # [(robot_id, ip, max_battery, poi_name, charging_id)]
            standby_robots = []    # [(robot_id, ip, poi_name, standby_id)]

            for r in active_robots:
                if not r.ip_address:
                    continue

                # 충전소에 있는 로봇
                if r.charging_id:
                    cpoi = db.query(MapPOI).filter(MapPOI.id == r.charging_id).first()
                    if cpoi and cpoi.name in ("C1", "C2", "C3"):
                        charging_robots.append({
                            "id": r.id, "ip": r.ip_address,
                            "max_battery": r.max_battery or 95,
                            "poi_name": cpoi.name, "charging_id": r.charging_id,
                        })
                # 대기장소에 있는 로봇
                if r.standby_id:
                    spoi = db.query(MapPOI).filter(MapPOI.id == r.standby_id).first()
                    if spoi and spoi.name in ("W1", "W2"):
                        standby_robots.append({
                            "id": r.id, "ip": r.ip_address,
                            "poi_name": spoi.name, "standby_id": r.standby_id,
                        })

            if not charging_robots or not standby_robots:
                _schedule_battery_rotation()
                return

            # 완충된 충전 로봇 선별 + 배터리 조회
            fully_charged = []
            for cr in charging_robots:
                pct = _get_battery_percentage(cr["ip"])
                if pct is None:
                    continue
                if pct >= cr["max_battery"]:
                    fully_charged.append({
                        **cr, "battery": pct,
                        "charge_start": _charging_start_time.get(cr["id"], time.time()),
                    })
                    # 완충 로봇의 충전 시작 시각이 없으면 현재로 기록
                    if cr["id"] not in _charging_start_time:
                        _charging_start_time[cr["id"]] = time.time()

            if not fully_charged:
                _schedule_battery_rotation()
                return

            # 오래 충전된 순으로 정렬 (오래된 순 우선 교체)
            fully_charged.sort(key=lambda x: x["charge_start"])

            # W 로봇 배터리 조회
            for wr in standby_robots:
                w_pct = _get_battery_percentage(wr["ip"])
                wr["battery"] = w_pct if w_pct is not None else 100.0

            # 배터리 낮은 W 로봇 순으로 정렬 (충전 필요한 순)
            standby_robots.sort(key=lambda x: x["battery"])

            # 교체 가능 수 = min(완충된 C 수, W 위치 수)
            swap_count = min(len(fully_charged), len(standby_robots))
            logger.info(f"[Battery Rotation] 완충 {len(fully_charged)}대, 대기 {len(standby_robots)}대 → {swap_count}번 교체")

            for i in range(swap_count):
                c_robot = fully_charged[i]
                w_robot = standby_robots[i]

                c_row = db.query(Robot).filter(Robot.id == c_robot["id"]).first()
                w_row = db.query(Robot).filter(Robot.id == w_robot["id"]).first()
                if not c_row or not w_row:
                    continue

                # W 로봇도 max_battery 이상이면 충전 불필요 → 교체 스킵
                w_max = w_row.max_battery or 95
                if w_robot["battery"] >= w_max:
                    logger.info(f"[Battery Rotation] 스킵: W 로봇 {w_robot['id']}({w_robot['battery']:.0f}%) >= "
                                f"max({w_max}%) — 이미 충전 충분")
                    continue

                # W 로봇이 C 로봇보다 배터리 높거나 같으면 교체 불필요
                if w_robot["battery"] >= c_robot["battery"]:
                    logger.info(f"[Battery Rotation] 스킵: W 로봇 {w_robot['id']}({w_robot['battery']:.0f}%) >= "
                                f"C 로봇 {c_robot['id']}({c_robot['battery']:.0f}%)")
                    continue

                # DB 위치 교환: C → W, W → C
                c_row.charging_id = None
                c_row.standby_id = w_robot["standby_id"]
                w_row.standby_id = None
                w_row.charging_id = c_robot["charging_id"]
                db.commit()

                logger.info(f"[Battery Rotation] 로봇 {c_robot['id']}({c_robot['poi_name']}) ↔ "
                            f"로봇 {w_robot['id']}({w_robot['poi_name']})")

                # 충전 시작 시각 정리: C에서 나간 로봇은 삭제, W에서 C로 간 로봇은 기록
                _charging_start_time.pop(c_robot["id"], None)
                _charging_start_time[w_robot["id"]] = time.time()

                # 순차 교체: W 로봇 먼저 C로 이동(충전 시작) → 완료 후 C 로봇이 W로 이동
                # 이유: 동시에 움직이면 경로 충돌, 같은 위치 도달 가능
                threading.Thread(
                    target=_rotate_swap_sequential,
                    args=(
                        w_robot["id"], w_robot["ip"], c_robot["poi_name"],
                        c_robot["id"], c_robot["ip"], w_robot["poi_name"],
                    ),
                    daemon=True,
                ).start()
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"[Battery Rotation] 실패: {e}")
    finally:
        _schedule_battery_rotation()


def _rotate_swap_sequential(
    w_id: int, w_ip: str, c_poi_name: str,
    c_id: int, c_ip: str, w_poi_name: str,
):
    """동시 교체: 양쪽 로봇이 동시에 출발 (standard 모드 장애물 회피)

    순차 실행 시 먼저 도착한 로봇이 길을 막는 문제 방지
    """
    try:
        logger.info(f"[Battery Rotation] 동시 출발: 로봇 {w_id}({w_poi_name} → {c_poi_name}), "
                     f"로봇 {c_id}({c_poi_name} → {w_poi_name})")
        t1 = threading.Thread(target=_rotate_robot_move, args=(w_id, w_ip, c_poi_name, "charging"), daemon=True)
        t2 = threading.Thread(target=_rotate_robot_move, args=(c_id, c_ip, w_poi_name, "standby"), daemon=True)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        logger.info(f"[Battery Rotation] 교체 완료: 로봇 {w_id} ↔ 로봇 {c_id}")
    except Exception as e:
        logger.warning(f"[Battery Rotation] 동시 교체 실패: {e}")


def _rotate_robot_move(robot_id: int, robot_ip: str, target_poi_name: str, target_type: str):
    """로테이션 이동 실행 (개별 로봇 스레드) — 직행, 실패 시 무한 재시도"""
    try:
        db = SessionLocal()
        try:
            poi = db.query(MapPOI).filter(
                MapPOI.name == target_poi_name, MapPOI.is_active == True,
            ).first()
            if not poi:
                logger.warning(f"[Rotate Robot {robot_id}] POI '{target_poi_name}' 없음")
                return
            tx = float(poi.world_x if poi.world_x is not None else poi.x)
            ty = float(poi.world_y if poi.world_y is not None else poi.y)
            t_angle = float(poi.angle or 0.0)
        finally:
            db.close()

        cancel_and_verify(robot_ip)
        time.sleep(1.0)
        move_lock = _get_move_lock(robot_id)
        stop_event = threading.Event()
        ws = None
        try:
            ws = _create_planning_ws(robot_ip)
        except Exception:
            pass

        ws, result, _ = _execute_move(
            robot_id, robot_ip, tx, ty, t_angle, "",
            ws, move_lock, stop_event)
        retry_count = 0
        while result != "succeeded":
            retry_count += 1
            logger.warning(f"[Rotate Robot {robot_id}] 이동 실패 ({result}) — 재시도 {retry_count}")
            cancel_and_verify(robot_ip)
            time.sleep(RECOVERY_DELAY)
            try:
                if ws: ws.close()
            except Exception:
                pass
            ws = None
            try:
                ws = _create_planning_ws(robot_ip)
            except Exception:
                pass
            ws, result, _ = _execute_move(
                robot_id, robot_ip, tx, ty, t_angle, "",
                ws, move_lock, stop_event)

        if target_type == "charging":
            time.sleep(1.0)
            send_charge(robot_ip, charger_name=target_poi_name)
            logger.info(f"[Rotate Robot {robot_id}] {target_poi_name} 충전 시작")
        else:
            logger.info(f"[Rotate Robot {robot_id}] {target_poi_name} 도착 (대기)")
        if ws:
            try: ws.close()
            except Exception: pass
    except Exception as e:
        logger.warning(f"[Rotate Robot {robot_id}] 이동 실패: {e}")


def _schedule_battery_rotation():
    """배터리 로테이션 타이머 예약 (3분 간격)"""
    global _battery_rotation_timer
    if _battery_rotation_stop.is_set():
        return
    t = threading.Timer(BATTERY_ROTATION_INTERVAL, _battery_rotation_check)
    t.daemon = True
    _battery_rotation_timer = t
    t.start()


def start_battery_rotation():
    """배터리 로테이션 스케줄러 시작"""
    _battery_rotation_stop.clear()
    _schedule_battery_rotation()
    logger.info(f"[Battery Rotation] 스케줄러 시작 — {BATTERY_ROTATION_INTERVAL}초 간격")


def stop_battery_rotation():
    """배터리 로테이션 스케줄러 중지"""
    global _battery_rotation_timer
    _battery_rotation_stop.set()
    if _battery_rotation_timer:
        _battery_rotation_timer.cancel()
        _battery_rotation_timer = None
    logger.info("[Battery Rotation] 스케줄러 중지")


# ─── 헬퍼: 다음 정지점 찾기 (태블릿 표시용) ──────────────────────────────────────

def _find_next_stop(work_pois, current_node_idx: int, stop_set: set) -> str:
    """현재 노드에서 순방향으로 가장 가까운 정지점 이름 반환"""
    n = len(work_pois)
    for offset in range(1, n + 1):
        check_idx = (current_node_idx + offset) % n
        if work_pois[check_idx].name in stop_set:
            return work_pois[check_idx].name
    return work_pois[current_node_idx].name


# ─── 개별 로봇 워커 ────────────────────────────────────────────────────────────

def _convoy_robot_worker(
    rc: dict,
    work_poi_names: list[str],
    stop_names: list[str],
    stop_event: threading.Event,
    graceful_event: threading.Event,
    wait_event: Optional[threading.Event],
    arrival_event: threading.Event,
    return_ready_event: threading.Event,
):
    """개별 로봇 워커 스레드

    1. 진입 경로 이동 (충전소 → WORK1)
    2. WORK1 도착 → arrival_event.set()
    3. 작업 루프 (WORK1→WORK6 무한 반복)
    4. 그레이스풀 정지 → WORK1 복귀 → 복귀 경로 → 충전
    """
    robot_id = rc["robot_id"]
    robot_ip = rc["ip"]
    entry_names = rc.get("entry_poi_names", [])
    return_names = rc.get("return_poi_names", [])
    charging_poi_name = rc.get("charging_poi_name")
    standby_poi_name = rc.get("standby_poi_name")
    start_poi_type = rc.get("start_poi_type", "charging")  # "charging" | "standby"

    ws = None
    move_lock = _get_move_lock(robot_id)

    try:
        # ── POI 좌표 조회 (DB 세션은 조회 후 즉시 반환) ──
        work_pois = []
        entry_pois = []
        return_pois = []
        charging_poi = None
        standby_poi = None

        db = SessionLocal()
        try:
            # ── 활성 맵 ID 자동 감지 (중복 POI 이름 방지) ──
            # 첫 번째 WORK POI로 가장 최근 활성 맵을 결정
            first_poi = db.query(MapPOI).join(RobotMap).filter(
                MapPOI.name == work_poi_names[0],
                MapPOI.is_active == True,
                RobotMap.is_active == True,
            ).order_by(RobotMap.id.desc()).first()
            if not first_poi:
                logger.error(f"[Robot {robot_id}] WORK POI '{work_poi_names[0]}' 없음")
                _update_robot_status(robot_id, "error", message=f"POI '{work_poi_names[0]}' 없음")
                return
            target_map_id = first_poi.map_id

            # convoy 전역 맵 ID 등록 (재배치 시 올바른 맵의 POI 사용)
            global _convoy_map_id
            with _convoy_lock:
                if _convoy_map_id is None:
                    _convoy_map_id = target_map_id

            for name in work_poi_names:
                poi = db.query(MapPOI).filter(
                    MapPOI.name == name, MapPOI.is_active == True,
                    MapPOI.map_id == target_map_id,
                ).first()
                if not poi:
                    logger.error(f"[Robot {robot_id}] WORK POI '{name}' 없음 (map_id={target_map_id})")
                    _update_robot_status(robot_id, "error", message=f"POI '{name}' 없음")
                    return
                db.expunge(poi)
                work_pois.append(poi)

            for name in entry_names:
                poi = db.query(MapPOI).filter(
                    MapPOI.name == name, MapPOI.is_active == True,
                    MapPOI.map_id == target_map_id,
                ).first()
                if not poi:
                    logger.error(f"[Robot {robot_id}] 진입 POI '{name}' 없음 (map_id={target_map_id})")
                    _update_robot_status(robot_id, "error", message=f"진입 POI '{name}' 없음")
                    return
                db.expunge(poi)
                entry_pois.append(poi)

            for name in return_names:
                poi = db.query(MapPOI).filter(
                    MapPOI.name == name, MapPOI.is_active == True,
                    MapPOI.map_id == target_map_id,
                ).first()
                if not poi:
                    logger.error(f"[Robot {robot_id}] 복귀 POI '{name}' 없음 (map_id={target_map_id})")
                    _update_robot_status(robot_id, "error", message=f"복귀 POI '{name}' 없음")
                    return
                db.expunge(poi)
                return_pois.append(poi)

            if charging_poi_name:
                charging_poi = db.query(MapPOI).filter(
                    MapPOI.name == charging_poi_name, MapPOI.is_active == True,
                    MapPOI.map_id == target_map_id,
                ).first()
                if not charging_poi:
                    logger.warning(f"[Robot {robot_id}] 충전소 POI '{charging_poi_name}' 없음 (map_id={target_map_id})")
                else:
                    db.expunge(charging_poi)

            if standby_poi_name:
                standby_poi = db.query(MapPOI).filter(
                    MapPOI.name == standby_poi_name, MapPOI.is_active == True,
                    MapPOI.map_id == target_map_id,
                ).first()
                if not standby_poi:
                    logger.warning(f"[Robot {robot_id}] 대기지점 POI '{standby_poi_name}' 없음 (map_id={target_map_id})")
                else:
                    db.expunge(standby_poi)

            # ── 배터리 최소값 / 로봇 표시명 조회 ──
            robot_row = db.query(Robot).filter(Robot.id == robot_id).first()
            min_battery = robot_row.min_battery if robot_row else 20
            robot_display = f"AMR{robot_row.wcs_no:02d}" if robot_row and robot_row.wcs_no else f"로봇 {robot_id}"

            # ── SVG→World 좌표 자동 변환 (world_x/y가 NULL인 POI) ──
            all_pois = work_pois + entry_pois + return_pois
            if charging_poi:
                all_pois.append(charging_poi)
            if standby_poi:
                all_pois.append(standby_poi)
            _ensure_world_coords(db, all_pois, robot_id)
        finally:
            db.close()  # POI 조회 완료 → DB 세션 즉시 반환

        stop_set = set(stop_names)

        # WebSocket 연결
        try:
            ws = _create_planning_ws(robot_ip)
        except Exception as e:
            logger.warning(f"[{robot_display}] WS 연결 실패 — HTTP 폴백: {e}")

        # ── 1단계: 앞 로봇 WORK1 도착 대기 ──
        if wait_event:
            _update_robot_status(robot_id, "waiting", message="앞 로봇 출발 대기")
            while not wait_event.is_set():
                if stop_event.is_set():
                    _update_robot_status(robot_id, "stopped")
                    return
                wait_event.wait(timeout=1.0)
            logger.info(f"[{robot_display}] 앞 로봇 도착 확인 → 출발")

        # ── 재개 모드 여부 확인 ──
        resume_node_index = rc.get("resume_node_index")  # None이면 신규 시작

        immediate_resume = rc.get("immediate_resume", False)

        if immediate_resume and resume_node_index is not None and 0 <= resume_node_index < len(work_pois):
            # ══ 즉시 재개: 현재 위치에서 바로 작업 루프 시작 (비상정지 후 다시 시작) ══
            resume_target_poi = work_pois[resume_node_index]
            logger.info(f"[{robot_display}] 즉시 재개 — {resume_target_poi.name}(node={resume_node_index})에서 작업 루프 시작")

            arrival_event.set()
            with _convoy_lock:
                _convoy_node_positions[robot_id] = resume_node_index

            # 정지점이면 확인 버튼 대기
            if resume_target_poi.name in set(stop_names):
                stop_list = [s for s in stop_names if s in set(stop_names)]
                if resume_target_poi.name == stop_list[0] if stop_list else False:
                    _imm_wait = "피킹 장소 대기"
                elif resume_target_poi.name == stop_list[-1] if stop_list else False:
                    _imm_wait = "투입 장소 대기"
                else:
                    _imm_wait = f"{resume_target_poi.name} 대기"

                _update_robot_status(robot_id, "waiting_confirmation",
                                     current_poi=resume_target_poi.name,
                                     message=_imm_wait)
                with _task_lock:
                    _run_info[robot_id] = {
                        "status": "waiting_confirmation",
                        "loop": 0,
                        "current_poi": resume_target_poi.name,
                        "message": _imm_wait,
                    }
                with _task_lock:
                    _imm_confirm = _confirm_events.get(robot_id)
                    if not _imm_confirm:
                        _imm_confirm = threading.Event()
                        _confirm_events[robot_id] = _imm_confirm
                try:
                    while not (stop_event.is_set() or graceful_event.is_set() or _imm_confirm.is_set()):
                        time.sleep(0.1)
                finally:
                    with _task_lock:
                        _confirm_events.pop(robot_id, None)
            else:
                _update_robot_status(robot_id, "running", current_poi=resume_target_poi.name)

            loop_count = 0
            current_node = resume_node_index

        elif resume_node_index is not None and 0 <= resume_node_index < len(work_pois):
            # ══ 재개 모드: 진입경로 → ENTER-LAST까지 트랙 → 저장 좌표로 직접 이동 ══
            resume_target_poi = work_pois[resume_node_index]
            resume_actual_x = rc.get("resume_actual_x")
            resume_actual_y = rc.get("resume_actual_y")
            resume_actual_ori = rc.get("resume_actual_ori")

            cancel_and_verify(robot_ip)

            # 목적지 결정: 실좌표 우선, 없으면 POI 좌표 폴백
            if resume_actual_x is not None and resume_actual_y is not None:
                tx = resume_actual_x
                ty = resume_actual_y
                t_angle = resume_actual_ori if resume_actual_ori is not None else 0.0
                logger.info(f"[{robot_display}] 재개 모드 — 진입경로 경유 → 실좌표({tx:.3f}, {ty:.3f})로 이동")
            else:
                tx = resume_target_poi.world_x if resume_target_poi.world_x is not None else resume_target_poi.x
                ty = resume_target_poi.world_y if resume_target_poi.world_y is not None else resume_target_poi.y
                t_angle = resume_target_poi.angle if resume_target_poi.angle is not None else 0.0
                logger.info(f"[{robot_display}] 재개 모드 — 진입경로 경유 → POI {resume_target_poi.name}로 이동")

            # 진입 경로(충전소 → ENTER-LAST)를 경유점으로 구성
            coords_parts = []
            for ep in entry_pois:
                ex = ep.world_x if ep.world_x is not None else ep.x
                ey = ep.world_y if ep.world_y is not None else ep.y
                coords_parts.extend([str(ex), str(ey)])
            route_coords = ",".join(coords_parts) if coords_parts else ""

            _update_robot_status(robot_id, "entering",
                                 current_poi=resume_target_poi.name,
                                 message="작업 위치로 이동 중")
            with _task_lock:
                _run_info[robot_id] = {
                    "status": "resuming",
                    "loop": 0,
                    "current_poi": resume_target_poi.name,
                    "message": "작업 위치로 이동 중",
                }

            # 진입경로 경유 → 저장 좌표로 이동
            ws, result, detail = _execute_move(
                robot_id, robot_ip, tx, ty, t_angle, route_coords,
                ws, move_lock, stop_event)

            if stop_event.is_set():
                _update_robot_status(robot_id, "stopped")
                return
            if result == "cancelled" and graceful_event.is_set():
                # 진입 중 정지 → 복귀 경로로 전환
                logger.info(f"[{robot_display}] 재개 진입 중 취소 — 복귀 경로로 전환")
                current_node = 0
                arrival_event.set()
                with _convoy_lock:
                    _convoy_node_positions[robot_id] = 0
                loop_count = 0
            elif result == "cancelled":
                _update_robot_status(robot_id, "stopped")
                return
            else:
                while result != "succeeded":
                    if stop_event.is_set() or graceful_event.is_set():
                        break
                    logger.warning(f"[{robot_display}] 재개 이동 실패 ({result}) — 재시도")
                    cancel_and_verify(robot_ip)
                    time.sleep(RECOVERY_DELAY)
                    try:
                        if ws: ws.close()
                    except Exception:
                        pass
                    ws = None
                    try:
                        ws = _create_planning_ws(robot_ip)
                    except Exception:
                        pass
                    ws, result, detail = _execute_move(
                        robot_id, robot_ip, tx, ty, t_angle, route_coords,
                        ws, move_lock, stop_event)
                if result == "succeeded":
                    # 정상 도착
                    logger.info(f"[{robot_display}] 재개 완료 — {resume_target_poi.name} 부근 도착")

                arrival_event.set()
                with _convoy_lock:
                    _convoy_node_positions[robot_id] = resume_node_index

                # 전원 도착 + 5초 딜레이 완료까지 대기
                _update_robot_status(robot_id, "waiting",
                                     current_poi=resume_target_poi.name,
                                     message="전원 도착 대기 중")
                while not _convoy_all_arrived.is_set():
                    if stop_event.is_set():
                        _update_robot_status(robot_id, "stopped")
                        return
                    _convoy_all_arrived.wait(timeout=1.0)

                # 정지점(WORK2/WORK4) 위에 있으면 확인 버튼 대기
                if resume_target_poi.name in set(stop_names):
                    # 실제 좌표가 정지점 근처(10cm)인지 확인
                    _on_stop = False
                    try:
                        _rpose = _get_robot_pose(robot_ip)
                        if _rpose:
                            _rtx = resume_target_poi.world_x if resume_target_poi.world_x is not None else resume_target_poi.x
                            _rty = resume_target_poi.world_y if resume_target_poi.world_y is not None else resume_target_poi.y
                            _rdist = ((_rpose[0] - _rtx)**2 + (_rpose[1] - _rty)**2) ** 0.5
                            _on_stop = _rdist <= 0.3  # 30cm 이내면 정지점 위에 있음
                            logger.info(f"[{robot_display}] 재개 위치 확인: {resume_target_poi.name} 거리={_rdist:.2f}m → {'대기' if _on_stop else '통과'}")
                    except Exception:
                        pass

                    if _on_stop:
                        stop_list = [s for s in stop_names if s in set(stop_names)]
                        if resume_target_poi.name == stop_list[0] if stop_list else False:
                            _rw = "피킹 장소 대기"
                        elif resume_target_poi.name == stop_list[-1] if stop_list else False:
                            _rw = "투입 장소 대기"
                        else:
                            _rw = f"{resume_target_poi.name} 대기"

                        _update_robot_status(robot_id, "waiting_confirmation",
                                             current_poi=resume_target_poi.name, message=_rw)
                        with _task_lock:
                            _run_info[robot_id] = {
                                "status": "waiting_confirmation",
                                "loop": 0,
                                "current_poi": resume_target_poi.name,
                                "message": _rw,
                            }
                        with _task_lock:
                            _rc = _confirm_events.get(robot_id)
                            if not _rc:
                                _rc = threading.Event()
                                _confirm_events[robot_id] = _rc
                        try:
                            while not (stop_event.is_set() or graceful_event.is_set() or _rc.is_set()):
                                time.sleep(0.1)
                        finally:
                            with _task_lock:
                                _confirm_events.pop(robot_id, None)
                    else:
                        _update_robot_status(robot_id, "running", current_poi=resume_target_poi.name)
                else:
                    _update_robot_status(robot_id, "running", current_poi=resume_target_poi.name)

                loop_count = 0
                current_node = resume_node_index

        else:
            # ══ 신규 시작: 기존 진입 로직 ══

            # 첫 정지점(WORK2)까지 한 번에 이동, WORK1은 통과
            first_stop_idx = 1  # WORK2 (첫 번째 정지점)
            for _si, _sp in enumerate(work_pois):
                if _sp.name in set(stop_names):
                    first_stop_idx = _si
                    break
            first_stop_poi = work_pois[first_stop_idx]

            if entry_pois:
                cancel_and_verify(robot_ip)

                # 진입 시작 → WORK1 기준으로 노드 위치 등록 (트랙 진입으로 간주)
                with _convoy_lock:
                    _convoy_node_positions[robot_id] = 0

                # entry_pois → WORK1 → ... → WORK2(첫 정지점) 한 번에 이동
                all_waypoints = list(entry_pois)
                for wi in range(0, first_stop_idx + 1):
                    all_waypoints.append(work_pois[wi])

                coords_parts = []
                for wp in all_waypoints:
                    wx = wp.world_x if wp.world_x is not None else wp.x
                    wy = wp.world_y if wp.world_y is not None else wp.y
                    coords_parts.extend([str(wx), str(wy)])

                tx = first_stop_poi.world_x if first_stop_poi.world_x is not None else first_stop_poi.x
                ty = first_stop_poi.world_y if first_stop_poi.world_y is not None else first_stop_poi.y
                t_angle = first_stop_poi.angle if first_stop_poi.angle is not None else 0.0
                route_coords = ",".join(coords_parts) if len(coords_parts) > 2 else ""

                wp_info = [(wp.name, wp.world_x, wp.world_y) for wp in all_waypoints]
                logger.info(f"[{robot_display}] 진입 POI: {wp_info}, target=({tx},{ty}), route_coords={route_coords}")

                _update_robot_status(robot_id, "entering",
                                     current_poi=first_stop_poi.name,
                                     message="피킹 장소로 이동 중")
                with _task_lock:
                    _run_info[robot_id] = {
                        "status": "moving_to_start",
                        "loop": 0,
                        "current_poi": first_stop_poi.name,
                        "next_stop": first_stop_poi.name,
                        "message": "피킹 장소로 이동 중",
                        "show_confirm": True,
                    }

                ws, result, detail = _execute_move(
                    robot_id, robot_ip, tx, ty, t_angle, route_coords,
                    ws, move_lock, stop_event)

                if stop_event.is_set():
                    _update_robot_status(robot_id, "stopped")
                    return
                if result == "cancelled" and graceful_event.is_set():
                    # 진입 중 정지 → 복귀 경로로 전환
                    logger.info(f"[{robot_display}] 진입 중 취소 — 복귀 경로로 전환")
                    current_node = 0
                    arrival_event.set()
                    with _convoy_lock:
                        _convoy_node_positions[robot_id] = 0
                    loop_count = 0
                    # 작업 루프 건너뛰고 바로 5단계(복귀)로 진행
                elif result == "cancelled":
                    _update_robot_status(robot_id, "stopped")
                    return
                else:
                    while result != "succeeded":
                        if stop_event.is_set() or graceful_event.is_set():
                            break
                        logger.warning(f"[{robot_display}] 진입 경로 실패 ({result}) — 재시도")
                        cancel_and_verify(robot_ip)
                        time.sleep(RECOVERY_DELAY)
                        try:
                            if ws: ws.close()
                        except Exception:
                            pass
                        ws = None
                        try:
                            ws = _create_planning_ws(robot_ip)
                        except Exception:
                            pass
                        ws, result, detail = _execute_move(
                            robot_id, robot_ip, tx, ty, t_angle, route_coords,
                            ws, move_lock, stop_event)
                    if result == "succeeded":
                        logger.info(f"[{robot_display}] {first_stop_poi.name} 이동 완료 (WORK1 통과)")

                # 진입 도착 검증: 실제 좌표 확인
                if result == "succeeded":
                    ENTRY_THRESHOLD = 0.10
                    _entry_arrived = False
                    # 버튼 이미 눌렸으면 검증 스킵
                    with _task_lock:
                        _pre_confirm = _confirm_events.get(robot_id)
                    if _pre_confirm and _pre_confirm.is_set():
                        logger.info(f"[{robot_display}] 진입 중 확인 버튼 눌림 — 도착 검증 스킵")
                        _entry_arrived = True
                    while not _entry_arrived:
                        if stop_event.is_set() or graceful_event.is_set():
                            break
                        try:
                            pose = _get_robot_pose(robot_ip)
                            if pose:
                                dx = pose[0] - tx
                                dy = pose[1] - ty
                                dist = (dx*dx + dy*dy) ** 0.5
                                if dist <= ENTRY_THRESHOLD:
                                    logger.info(f"[{robot_display}] 진입 도착 확인 OK "
                                                f"({first_stop_poi.name}, 거리={dist:.3f}m)")
                                    _entry_arrived = True
                                else:
                                    logger.warning(f"[{robot_display}] 진입 미도착 "
                                                   f"(거리={dist:.2f}m) → standard 재이동")
                                    with _task_lock:
                                        _run_info[robot_id] = {
                                            "status": "moving_to_start",
                                            "loop": 0,
                                            "current_poi": first_stop_poi.name,
                                            "message": "피킹 장소로 이동 중",
                                            "show_confirm": True,
                                        }
                                    cancel_and_verify(robot_ip)
                                    time.sleep(RECOVERY_DELAY)
                                    try:
                                        if ws: ws.close()
                                    except Exception:
                                        pass
                                    ws = None
                                    try:
                                        ws = _create_planning_ws(robot_ip)
                                    except Exception:
                                        pass
                                    ws, result, detail = _execute_move(
                                        robot_id, robot_ip, tx, ty, t_angle, route_coords,
                                        ws, move_lock, stop_event, target_accuracy=0.03,
                                        cancel_on_stuck=True, stuck_delay=2.5)
                            else:
                                _entry_arrived = True
                        except Exception:
                            _entry_arrived = True

            else:
                cancel_and_verify(robot_ip)

            # cancelled+graceful이 아닌 경우만 정상 진입 완료 처리
            if not (result == "cancelled" and graceful_event.is_set()):
                arrival_event.set()
                with _convoy_lock:
                    _convoy_node_positions[robot_id] = first_stop_idx

                # 첫 도착 정지점 대기 (피킹 장소 대기 + 확인)
                _update_robot_status(robot_id, "waiting_confirmation",
                                     current_poi=first_stop_poi.name,
                                     message="피킹 장소 대기")
                with _task_lock:
                    _run_info[robot_id] = {
                        "status": "waiting_confirmation",
                        "loop": 0,
                        "current_poi": first_stop_poi.name,
                        "message": "피킹 장소 대기",
                    }
                with _task_lock:
                    confirm_event = _confirm_events.get(robot_id)
                    if not confirm_event:
                        confirm_event = threading.Event()
                        _confirm_events[robot_id] = confirm_event
                try:
                    while not (stop_event.is_set() or graceful_event.is_set() or confirm_event.is_set()):
                        time.sleep(0.1)
                finally:
                    with _task_lock:
                        _confirm_events.pop(robot_id, None)

                _update_robot_status(robot_id, "running", current_poi=first_stop_poi.name)
                loop_count = 0
                current_node = first_stop_idx
        graceful_finishing = False
        low_battery_break = False

        # WORK4 인덱스 미리 계산 (마지막 정지점)
        work4_node = None
        for _si, _sp in enumerate(work_pois):
            if _sp.name in stop_set:
                work4_node = _si  # 마지막 stop_set 노드 = WORK4
        if work4_node is None:
            work4_node = len(work_pois) - 1  # fallback

        # 개별 복귀 이벤트 참조
        my_return_event = _convoy_return_events.get(robot_id)

        while not stop_event.is_set():
            # ── 매 노드 도착: 그레이스풀 + 개별 복귀 이벤트 체크 ──
            # graceful_event: 전체 정지 신호 (순차 복귀 스케줄러 시작)
            # my_return_event: 이 로봇의 실제 복귀 차례
            if graceful_event.is_set():
                # 내 차례가 올 때까지 대기 (1초 단위 체크)
                while my_return_event and not my_return_event.is_set():
                    if stop_event.is_set():
                        break
                    _update_robot_status(robot_id, "finishing",
                                         message=f"복귀 대기 중 ({work_pois[current_node].name})")
                    my_return_event.wait(timeout=1.0)

                if not graceful_finishing:
                    graceful_finishing = True
                    # 실제 복귀 시점의 좌표 + 노드로 저장 상태 갱신
                    _update_saved_position(robot_id, robot_ip)
                    logger.info(f"[{robot_display}] 순차 복귀 — 현재 위치({work_pois[current_node].name})에서 복귀 시작")
                    if not _convoy_reassign_done.is_set():
                        with _convoy_hot_swap_lock:
                            if not _convoy_reassign_done.is_set():
                                _reassign_convoy_positions(map_id=target_map_id)
                                _convoy_reassign_done.set()
                            else:
                                _convoy_reassign_done.wait(timeout=10)
                    else:
                        _convoy_reassign_done.wait(timeout=10)
                break  # 현재 위치에서 바로 복귀 경로로

            # ── WORK4 도착 시 배터리/시간 체크 ──
            if current_node == work4_node:
                # 시간 기반/배터리 복귀 완주
                if low_battery_break:
                    break

                loop_count += 1

                # 최소 배터리 임계값 체크 (2회차 루프부터)
                if not graceful_finishing and loop_count > 1:
                    batt = _get_battery_percentage(robot_ip)
                    if batt is not None:
                        _convoy_battery_cache[robot_id] = batt
                    if batt is not None and batt < min_battery:
                        logger.info(f"[{robot_display}] 배터리 {batt:.1f}% < 최소 {min_battery}% → 복귀")
                        _update_robot_status(robot_id, "low_battery",
                                             message=f"배터리 부족 ({batt:.1f}%) — 충전소 귀환")
                        low_battery_break = True
                        # 먼저 convoy 목록에서 제거 → 재배치 시 복귀 로봇 제외
                        with _convoy_lock:
                            _convoy_robots[:] = [r for r in _convoy_robots if r["robot_id"] != robot_id]
                            _convoy_return_requested.discard(robot_id)
                            _convoy_node_positions.pop(robot_id, None)
                        # DB 저장 상태도 삭제
                        try:
                            _db = SessionLocal()
                            _db.query(ConvoySavedState).filter(ConvoySavedState.robot_id == robot_id).delete()
                            _db.commit()
                            _db.close()
                            logger.info(f"[{robot_display}] 배터리 복귀 — DB 저장 상태 삭제")
                        except Exception:
                            pass
                        with _convoy_hot_swap_lock:
                            _reassign_convoy_positions(map_id=target_map_id)
                        break  # WORK4에서 바로 복귀 경로

                # 시간 기반 복귀 요청 체크
                if not low_battery_break and not graceful_finishing:
                    with _convoy_lock:
                        requested = robot_id in _convoy_return_requested
                    if requested:
                        battery_pct = _get_battery_percentage(robot_ip)
                        if battery_pct is not None:
                            _convoy_battery_cache[robot_id] = battery_pct
                        pct_str = f"{battery_pct:.1f}%" if battery_pct is not None else "?"
                        logger.info(f"[{robot_display}] 시간 기반 복귀 요청 (배터리: {pct_str}) → 복귀")
                        _update_robot_status(robot_id, "low_battery",
                                             message=f"시간 기반 복귀 ({pct_str}) — 충전소 귀환")
                        low_battery_break = True
                        # 먼저 convoy 목록에서 제거 → 재배치 시 복귀 로봇 제외
                        with _convoy_lock:
                            _convoy_robots[:] = [r for r in _convoy_robots if r["robot_id"] != robot_id]
                            _convoy_return_requested.discard(robot_id)
                            _convoy_node_positions.pop(robot_id, None)
                        # DB 저장 상태도 삭제
                        try:
                            _db = SessionLocal()
                            _db.query(ConvoySavedState).filter(ConvoySavedState.robot_id == robot_id).delete()
                            _db.commit()
                            _db.close()
                            logger.info(f"[{robot_display}] 시간 기반 복귀 — DB 저장 상태 삭제")
                        except Exception:
                            pass
                        with _convoy_hot_swap_lock:
                            _reassign_convoy_positions(map_id=target_map_id)
                        break  # WORK4에서 바로 복귀 경로

            # ── 다음 정지 목표 계산 (통과 노드를 묶어 한 번에 이동) ──
            current_poi = work_pois[current_node]
            segment_nodes = []
            scan = current_node
            while True:
                scan = (scan + 1) % len(work_pois)
                segment_nodes.append(scan)
                if work_pois[scan].name in stop_set:
                    break

            dest_node = segment_nodes[-1]
            dest_poi = work_pois[dest_node]
            next_stop_name = _find_next_stop(work_pois, current_node, stop_set)

            if stop_event.is_set():
                break

            # 이동 시작 전 graceful 체크 (정지 버튼 후 다음 이동 방지)
            if graceful_event.is_set():
                continue  # 루프 상단에서 break 처리

            # WS 없으면 재연결
            if ws is None:
                try:
                    ws = _create_planning_ws(robot_ip)
                except Exception as e:
                    logger.warning(f"[{robot_display}] 이동 전 WS 재연결 실패 — HTTP 폴백: {e}")

            # ── 경로 좌표 구성 (현재 노드 → 중간 노드들 → 목적지) ──
            coords_parts = []
            cx = current_poi.world_x if current_poi.world_x is not None else current_poi.x
            cy = current_poi.world_y if current_poi.world_y is not None else current_poi.y
            coords_parts.extend([str(cx), str(cy)])
            for sn in segment_nodes:
                sp = work_pois[sn]
                sx = sp.world_x if sp.world_x is not None else sp.x
                sy = sp.world_y if sp.world_y is not None else sp.y
                coords_parts.extend([str(sx), str(sy)])

            tx = float(dest_poi.world_x if dest_poi.world_x is not None else dest_poi.x)
            ty = float(dest_poi.world_y if dest_poi.world_y is not None else dest_poi.y)
            t_angle = dest_poi.angle if dest_poi.angle is not None else 0.0
            route_coords = ",".join(coords_parts)

            is_stop_point = dest_poi.name in stop_set
            segment_names = [work_pois[sn].name for sn in segment_nodes]

            # 투입/배출 구분: 첫 번째 정지점 = 투입, 마지막 정지점 = 배출
            stop_list = [s for s in stop_names if s in stop_set]
            if dest_poi.name == stop_list[0] if stop_list else False:
                move_display = "피킹 장소로 이동 중"
            elif dest_poi.name == stop_list[-1] if stop_list else False:
                move_display = "투입 장소로 이동 중"
            else:
                move_display = f"{dest_poi.name}(으)로 이동 중"

            status_msg = "finishing" if graceful_finishing else "running"
            _update_robot_status(robot_id, status_msg,
                                 current_poi=dest_poi.name, loop=loop_count,
                                 message=move_display)
            # 정지점이면 confirm_event 미리 등록 + 버튼 표시
            confirm_event = None
            wait_display = ""
            if is_stop_point:
                stop_list = [s for s in stop_names if s in stop_set]
                if dest_poi.name == stop_list[0] if stop_list else False:
                    wait_display = "피킹 장소 대기"
                elif dest_poi.name == stop_list[-1] if stop_list else False:
                    wait_display = "투입 장소 대기"
                else:
                    wait_display = f"{dest_poi.name} 대기"
                with _task_lock:
                    confirm_event = _confirm_events.get(robot_id)
                    if not confirm_event:
                        confirm_event = threading.Event()
                        _confirm_events[robot_id] = confirm_event
                    _run_info[robot_id] = {
                        "status": "running", "loop": loop_count,
                        "current_poi": dest_poi.name,
                        "next_stop": next_stop_name,
                        "message": move_display,
                        "show_confirm": True,
                    }
            else:
                with _task_lock:
                    _run_info[robot_id] = {
                        "status": "running", "loop": loop_count,
                        "current_poi": dest_poi.name,
                        "next_stop": next_stop_name,
                        "message": move_display,
                    }

            # ── 이동 실행 — 실제 좌표가 오차범위 안에 올 때까지 반복 ──
            stop_accuracy = 0.03 if is_stop_point else None
            ARRIVAL_THRESHOLD = 0.10 if is_stop_point else 0.5  # 정지점 10cm, 일반 50cm
            _first_move = True
            _arrived = False

            while not _arrived:
                if stop_event.is_set() or graceful_event.is_set():
                    break
                if confirm_event and confirm_event.is_set():
                    logger.info(f"[{robot_display}] 확인 버튼 눌림 — 도착 검증 스킵")
                    _arrived = True
                    break

                # 항상 트랙 경로로 이동 (재시도 포함)
                ws, result, detail = _execute_move(
                    robot_id, robot_ip, tx, ty, t_angle, route_coords,
                    ws, move_lock, stop_event, target_accuracy=stop_accuracy,
                    cancel_on_stuck=True, stuck_delay=2.5)

                if stop_event.is_set() or graceful_event.is_set():
                    break
                if result == "cancelled":
                    break

                # 실제 좌표 확인
                try:
                    pose = _get_robot_pose(robot_ip)
                    if pose:
                        dx = pose[0] - tx
                        dy = pose[1] - ty
                        dist = (dx*dx + dy*dy) ** 0.5
                        if dist <= ARRIVAL_THRESHOLD:
                            logger.info(f"[{robot_display}] 도착 확인 OK "
                                        f"({dest_poi.name}, 거리={dist:.3f}m)")
                            _arrived = True
                        else:
                            logger.warning(f"[{robot_display}] 미도착 "
                                           f"({dest_poi.name}, 거리={dist:.2f}m) → standard 재이동")
                            _update_robot_status(robot_id, "running",
                                                 current_poi=dest_poi.name, loop=loop_count,
                                                 message=f"{dest_poi.name} 이동 대기 중")
                            if is_stop_point:
                                with _task_lock:
                                    _run_info[robot_id] = {
                                        "status": "running", "loop": loop_count,
                                        "current_poi": dest_poi.name,
                                        "message": move_display,
                                        "show_confirm": True,
                                    }
                            cancel_and_verify(robot_ip)
                            time.sleep(RECOVERY_DELAY)
                            try:
                                if ws: ws.close()
                            except Exception:
                                pass
                            ws = None
                            try:
                                ws = _create_planning_ws(robot_ip)
                            except Exception:
                                pass
                    else:
                        logger.warning(f"[{robot_display}] 위치 조회 실패 → succeeded 신뢰")
                        _arrived = True
                except Exception as e:
                    logger.warning(f"[{robot_display}] 도착 검증 실패: {e} → succeeded 신뢰")
                    _arrived = True

            if stop_event.is_set():
                break
            if result == "cancelled" and graceful_event.is_set():
                logger.info(f"[{robot_display}] 이동 취소 — 순차 복귀 대기")
                break
            if result == "cancelled":
                break

            # ── 도착: 위치 갱신 (묶인 노드 모두 통과 완료) ──
            with _convoy_lock:
                _convoy_node_positions[robot_id] = dest_node
            current_node = dest_node

            # 이동 완료 후 그레이스풀 신호 수신 → 정지점 대기 건너뛰고 즉시 루프 상단으로
            if graceful_event.is_set():
                logger.info(f"[{robot_display}] 그레이스풀 신호 — {work_pois[current_node].name} 도착 즉시 복귀 전환")
                continue  # 루프 상단에서 break + 순차 복귀 대기 처리

            # ── 정지점이면 확인 대기 (이동 전 미리 버튼 표시, 도착 후 대기) ──
            if is_stop_point and confirm_event:
                _update_robot_status(robot_id, "waiting_confirmation",
                                     current_poi=dest_poi.name, loop=loop_count,
                                     message=wait_display)

                # 이미 눌렸으면 바로 진행, 아니면 대기
                if not confirm_event.is_set():
                    try:
                        while not (stop_event.is_set() or graceful_event.is_set() or confirm_event.is_set()):
                            time.sleep(0.1)
                    finally:
                        with _task_lock:
                            _confirm_events.pop(robot_id, None)
                else:
                    logger.info(f"[{robot_display}] 이동 중 확인 완료 — 바로 진행")
                    with _task_lock:
                        _confirm_events.pop(robot_id, None)

                with _task_lock:
                    _run_info[robot_id] = {
                        "status": "running", "loop": loop_count,
                        "current_poi": dest_poi.name,
                        "next_stop": next_stop_name,
                        "message": f"{dest_poi.name} 확인 완료",
                    }

                if stop_event.is_set():
                    break

                _update_robot_status(robot_id, "running",
                                     current_poi=dest_poi.name, loop=loop_count)

        # ── 5단계: 그레이스풀 정지 / 배터리 부족 → 충전소/대기소 직행 복귀 ──
        # 비상정지(stop_event만 set, graceful 아님) → 즉시 종료, 복귀 안 함
        if stop_event.is_set() and not graceful_event.is_set() and not low_battery_break:
            _update_robot_status(robot_id, "stopped", message="비상정지")
            return

        if graceful_event.is_set() or stop_event.is_set() or low_battery_break:

            # 이동 취소 후 실제 멈춘 위치로 DB 갱신
            if graceful_event.is_set():
                _update_saved_position(robot_id, robot_ip)

            # 순차 복귀 대기: graceful이고 stop_event가 아닌 경우, 내 차례까지 대기
            if graceful_event.is_set() and not stop_event.is_set() and not low_battery_break:

                my_return_event = _convoy_return_events.get(robot_id)
                while my_return_event and not my_return_event.is_set():
                    if stop_event.is_set():
                        break
                    _update_robot_status(robot_id, "finishing",
                                         message=f"복귀 대기 중 ({work_pois[current_node].name})")
                    my_return_event.wait(timeout=1.0)
                logger.info(f"[{robot_display}] 순차 복귀 차례 도달 — 복귀 시작")

                # 재배치 1회 실행
                if not _convoy_reassign_done.is_set():
                    with _convoy_hot_swap_lock:
                        if not _convoy_reassign_done.is_set():
                            _reassign_convoy_positions(map_id=target_map_id)
                            _convoy_reassign_done.set()

            # 노드 위치 유지 (트랙 안이면 재시작 시 이어진행 가능)

            # ── DB에서 최신 위치 재조회 (배터리 재배치 반영) ──
            _cur_start_type = start_poi_type
            _cur_charging_poi = charging_poi
            _cur_standby_poi = standby_poi
            _cur_return_pois = return_pois

            db2 = SessionLocal()
            try:
                robot_row2 = db2.query(Robot).filter(Robot.id == robot_id).first()
                if not robot_row2:
                    logger.warning(f"[{robot_display}] DB 로봇 행 없음 — 기본 복귀경로 사용")
                elif not robot_row2.standby_id and not robot_row2.charging_id:
                    logger.warning(f"[{robot_display}] standby_id/charging_id 미설정 — 기본 복귀경로 사용")
                elif robot_row2.standby_id or robot_row2.charging_id:
                    # 로컬 변수에 먼저 조회 → 성공 시에만 _cur_* 변수 갱신
                    _new_return_pois = []
                    _new_dest_poi = None
                    _new_type = None

                    current_map_id = work_pois[0].map_id

                    # 배터리 부족 복귀 시 → 빈 충전소 탐색 (charging_id 없어도)
                    if low_battery_break:
                        # 다른 로봇이 점유하지 않은 빈 충전소 탐색
                        occupied_poi_ids = set()
                        for r in db2.query(Robot).filter(
                            Robot.is_active == True, Robot.id != robot_id
                        ).all():
                            if r.charging_id:
                                occupied_poi_ids.add(r.charging_id)
                            if r.standby_id:
                                occupied_poi_ids.add(r.standby_id)
                        free_cpoi = None
                        for cname in ["C1", "C2", "C3"]:
                            cpoi = db2.query(MapPOI).filter(
                                MapPOI.name == cname, MapPOI.is_active == True,
                                MapPOI.map_id == current_map_id,
                            ).first()
                            if cpoi and cpoi.id not in occupied_poi_ids:
                                free_cpoi = cpoi
                                break
                        if free_cpoi:
                            robot_row2.charging_id = free_cpoi.id
                            robot_row2.standby_id = None
                            db2.commit()
                        elif charging_poi:
                            # 빈 충전소 없으면 원래 출발 충전소로 복귀
                            robot_row2.charging_id = charging_poi.id
                            robot_row2.standby_id = None
                            db2.commit()
                            logger.warning(f"[{robot_display}] 빈 충전소 없음 — 원래 충전소 '{charging_poi.name}'으로 복귀")
                        else:
                            logger.warning(f"[{robot_display}] 빈 충전소 없음, 원래 충전소도 없음 — 기존 위치 사용")

                    # 배터리 부족 복귀 → 반드시 충전소, 그레이스풀 복귀 → standby 우선
                    use_charging_first = low_battery_break
                    if robot_row2.standby_id and not use_charging_first:
                        # 현재 맵 기준으로 POI 이름 조회 (구버전 맵 POI 방지)
                        ref_poi = db2.query(MapPOI).filter(
                            MapPOI.id == robot_row2.standby_id
                        ).first()
                        ref_name = ref_poi.name if ref_poi else None
                        spoi = db2.query(MapPOI).filter(
                            MapPOI.name == ref_name, MapPOI.is_active == True,
                            MapPOI.map_id == current_map_id,
                        ).first() if ref_name else None
                        if spoi:
                            db2.expunge(spoi)
                            _new_dest_poi = spoi
                            _new_type = "standby"
                            new_return_names = ["ENTER-LAST", f"{spoi.name}-1"]
                        else:
                            logger.warning(f"[{robot_display}] standby POI '{ref_name}' 없음 (map_id={current_map_id})")
                    if robot_row2.charging_id and (_new_dest_poi is None or use_charging_first):
                        ref_poi = db2.query(MapPOI).filter(
                            MapPOI.id == robot_row2.charging_id
                        ).first()
                        ref_name = ref_poi.name if ref_poi else None
                        cpoi = db2.query(MapPOI).filter(
                            MapPOI.name == ref_name, MapPOI.is_active == True,
                            MapPOI.map_id == current_map_id,
                        ).first() if ref_name else None
                        if cpoi:
                            db2.expunge(cpoi)
                            _new_dest_poi = cpoi
                            _new_type = "charging"
                            new_return_names = ["ENTER-LAST", f"{cpoi.name}-1"]
                        else:
                            logger.warning(f"[{robot_display}] charging POI '{ref_name}' 없음 (map_id={current_map_id})")

                    if _new_dest_poi and _new_type:
                        for rn in new_return_names:
                            rp = db2.query(MapPOI).filter(
                                MapPOI.name == rn, MapPOI.is_active == True,
                                MapPOI.map_id == work_pois[0].map_id,
                            ).first()
                            if rp:
                                db2.expunge(rp)
                                _new_return_pois.append(rp)
                            else:
                                logger.warning(f"[{robot_display}] 복귀 경유 POI '{rn}' 없음 (map_id={work_pois[0].map_id})")

                        if _new_return_pois:
                            all_coord_pois = _new_return_pois + [_new_dest_poi]
                            _ensure_world_coords(db2, all_coord_pois, robot_id)

                            # 모든 조회 성공 → _cur_* 갱신
                            _cur_return_pois = _new_return_pois
                            if _new_type == "standby":
                                _cur_standby_poi = _new_dest_poi
                                _cur_charging_poi = None
                            else:
                                _cur_charging_poi = _new_dest_poi
                                _cur_standby_poi = None
                            _cur_start_type = _new_type
                        else:
                            logger.warning(f"[{robot_display}] 복귀 경유 POI 모두 없음 — 기본 복귀경로 사용: "
                                           f"{[p.name for p in return_pois]}")
            except Exception as e:
                logger.warning(f"[{robot_display}] 위치 재조회 실패 — 기본 복귀경로 사용: {e}")
                # 예외 시 원래 값 복원 (부분 변경 방지)
                _cur_start_type = start_poi_type
                _cur_charging_poi = charging_poi
                _cur_standby_poi = standby_poi
                _cur_return_pois = return_pois
            finally:
                db2.close()

            # ── 복귀 경로 이동 (현재위치 → WORK1 경유 → 충전소/대기소 직행) ──
            if not _cur_return_pois:
                logger.error(f"[{robot_display}] 복귀 경유 POI 없음! "
                             f"WORK1에서 직접 충전 명령 시도 — 거리가 멀면 실패할 수 있음")
            if _cur_return_pois:
                _update_robot_status(robot_id, "charging_route",
                                     message="복귀 장소로 이동 중")
                with _task_lock:
                    _run_info[robot_id] = {
                        "status": "charging_route",
                        "message": "복귀 장소로 이동 중",
                    }

                target_poi = _cur_return_pois[-1]
                tx = target_poi.world_x if target_poi.world_x is not None else target_poi.x
                ty = target_poi.world_y if target_poi.world_y is not None else target_poi.y
                t_angle = target_poi.angle if target_poi.angle is not None else 0.0

                if low_battery_break:
                    # 배터리 복귀: 트랙 전체 경유 (현재노드+1 → ... → WORK1 → ENTER-LAST → 목적지)
                    coords_parts = []
                    if current_node != 0:
                        scan = current_node
                        while True:
                            scan = (scan + 1) % len(work_pois)
                            sp = work_pois[scan]
                            sx = sp.world_x if sp.world_x is not None else sp.x
                            sy = sp.world_y if sp.world_y is not None else sp.y
                            coords_parts.extend([str(sx), str(sy)])
                            if scan == 0:
                                break
                    else:
                        w1 = work_pois[0]
                        coords_parts.extend([
                            str(w1.world_x if w1.world_x is not None else w1.x),
                            str(w1.world_y if w1.world_y is not None else w1.y),
                        ])
                    for rp in _cur_return_pois:
                        rx = rp.world_x if rp.world_x is not None else rp.x
                        ry = rp.world_y if rp.world_y is not None else rp.y
                        coords_parts.extend([str(rx), str(ry)])
                    route_coords = ",".join(coords_parts) if len(coords_parts) > 2 else ""
                    ws, result, detail = _execute_move(
                        robot_id, robot_ip, tx, ty, t_angle, route_coords,
                        ws, move_lock, stop_event)
                else:
                    # 그레이스풀 복귀: standard 자율 내비게이션 — 장애물 자동 회피
                    ws, result, detail = _execute_move(
                        robot_id, robot_ip, tx, ty, t_angle, "",
                        ws, move_lock, stop_event)

                while result != "succeeded":
                    if stop_event.is_set():
                        break
                    logger.warning(f"[{robot_display}] 복귀 경로 실패 ({result}) — 재시도")
                    cancel_and_verify(robot_ip)
                    time.sleep(RECOVERY_DELAY)
                    try:
                        if ws: ws.close()
                    except Exception:
                        pass
                    ws = None
                    try:
                        ws = _create_planning_ws(robot_ip)
                    except Exception:
                        pass
                    ws, result, detail = _execute_move(
                        robot_id, robot_ip, tx, ty, t_angle, "",
                        ws, move_lock, stop_event)

            # ── 최종 목적지: 충전소 도킹 또는 대기지점 이동 ──
            if _cur_start_type == "standby" and _cur_standby_poi:
                sx = _cur_standby_poi.world_x if _cur_standby_poi.world_x is not None else _cur_standby_poi.x
                sy = _cur_standby_poi.world_y if _cur_standby_poi.world_y is not None else _cur_standby_poi.y
                s_angle = _cur_standby_poi.angle if _cur_standby_poi.angle is not None else 0.0

                ws, result, detail = _execute_move(
                    robot_id, robot_ip, sx, sy, s_angle, "",
                    ws, move_lock, stop_event)

                while result != "succeeded":
                    if stop_event.is_set():
                        break
                    logger.warning(f"[{robot_display}] 대기지점 이동 실패 ({result}) — 재시도")
                    cancel_and_verify(robot_ip)
                    time.sleep(RECOVERY_DELAY)
                    try:
                        if ws: ws.close()
                    except Exception:
                        pass
                    ws = None
                    try:
                        ws = _create_planning_ws(robot_ip)
                    except Exception:
                        pass
                    ws, result, detail = _execute_move(
                        robot_id, robot_ip, sx, sy, s_angle, "",
                        ws, move_lock, stop_event)

                _update_robot_status(robot_id, "standby", message="대기 중")
                with _task_lock:
                    _run_info[robot_id] = {
                        "status": "standby",
                        "message": "대기 중",
                    }
                log_activity("robot", "robot_standby_arrive",
                             f"{robot_display} 대기지점 복귀 완료",
                             robot_id=robot_id, robot_name=robot_display, source="_convoy_robot_worker")
            else:
                time.sleep(1)
                cname = _cur_charging_poi.name if _cur_charging_poi else None
                logger.info(f"[{robot_display}] 충전소 도킹 시도: charger_name={cname}, ip={robot_ip}")
                charge_ok, charge_msg = send_charge(robot_ip, charger_name=cname)
                if not charge_ok:
                    logger.error(f"[{robot_display}] 충전소 도킹 실패: {charge_msg}")
                    # 재시도 1회
                    time.sleep(3)
                    logger.info(f"[{robot_display}] 충전소 도킹 재시도")
                    charge_ok, charge_msg = send_charge(robot_ip, charger_name=cname)
                    if not charge_ok:
                        logger.error(f"[{robot_display}] 충전소 도킹 재시도 실패: {charge_msg}")
                else:
                    logger.info(f"[{robot_display}] 충전소 도킹 성공: {charge_msg}")

                _update_robot_status(robot_id, "charging", message="충전 중")

                with _task_lock:
                    _run_info[robot_id] = {
                        "status": "charging",
                        "message": "충전 중",
                    }
                log_activity("robot", "robot_charging_arrive",
                             f"{robot_display} 충전소 복귀 완료 — 충전 시작",
                             robot_id=robot_id, robot_name=robot_display, source="_convoy_robot_worker")

            # ── 배터리 부족 복귀 시: 먼저 대기 로봇 투입, 그 다음 자신을 pool에 재등록 ──
            if low_battery_break and not stop_event.is_set() and not graceful_event.is_set():
                # 1) 대기 풀에서 교체 로봇 투입 (자신이 아닌 다른 로봇)
                logger.info(f"[{robot_display}] 복귀 완료 → 대기 로봇 투입")
                _trigger_standby_robot()

                # 2) 자신을 standby pool에 재등록 (투입 후에 등록해야 자기 자신이 안 뽑힘)
                cur_pos_name = None
                if _cur_charging_poi:
                    cur_pos_name = _cur_charging_poi.name
                elif _cur_standby_poi:
                    cur_pos_name = _cur_standby_poi.name
                if not cur_pos_name:
                    cur_pos_name = rc.get("charging_poi_name") or rc.get("standby_poi_name")

                requeue_rc = {
                    **rc,
                    "start_poi_type": _cur_start_type,
                    "charging_poi_name": (
                        _cur_charging_poi.name if _cur_charging_poi
                        else rc.get("charging_poi_name")
                    ),
                    "standby_poi_name": (
                        _cur_standby_poi.name if _cur_standby_poi
                        else rc.get("standby_poi_name")
                    ),
                }
                if cur_pos_name:
                    requeue_rc["entry_poi_names"] = [f"{cur_pos_name}-1", "ENTER-LAST"]
                    requeue_rc["return_poi_names"] = ["ENTER-LAST", f"{cur_pos_name}-1"]
                    logger.info(f"[{robot_display}] standby pool 재등록 — "
                                f"현재 위치: {cur_pos_name}, 진입경로: {requeue_rc['entry_poi_names']}")

                _schedule_requeue(robot_id, robot_ip, requeue_rc)

            # return_ready_event 세팅 (앞 로봇 복귀 허용)
            return_ready_event.set()
            return

        # 정상 종료 (stop_event에 의한)
        _update_robot_status(robot_id, "stopped")
        return_ready_event.set()

    except Exception as e:
        logger.exception(f"[{robot_display}] 워커 예외: {e}")
        _update_robot_status(robot_id, "error", message=str(e))
        log_activity("robot", "robot_worker_error",
                     f"{robot_display} 워커 에러: {e}",
                     robot_id=robot_id, robot_name=robot_display, source="_convoy_robot_worker")
        arrival_event.set()  # 뒤 로봇 블록 방지
        return_ready_event.set()
    finally:
        if ws:
            try:
                ws.close()
            except Exception:
                pass
        # 노드 위치 정리 (비정상 종료 시 안전장치)
        with _convoy_lock:
            _convoy_node_positions.pop(robot_id, None)
        # 태블릿 상태 정리
        with _task_lock:
            _confirm_events.pop(robot_id, None)
            _stuck_states.pop(robot_id, None)
        logger.info(f"[{robot_display}] 워커 스레드 종료")


# ─── 헬퍼 함수들 ──────────────────────────────────────────────────────────────

def _update_robot_status(robot_id: int, status: str, **kwargs):
    """convoy 로봇 상태 업데이트 (convoy 상태 + 태블릿용 _run_info 동시 업데이트)"""
    with _convoy_lock:
        _convoy_robot_status[robot_id] = {"status": status, **kwargs}
    with _task_lock:
        _run_info[robot_id] = {"status": status, **kwargs}


def _update_all_status_message(message: str):
    """모든 convoy 로봇의 상태 메시지 일괄 업데이트"""
    with _convoy_lock:
        for rid in _convoy_robot_status:
            _convoy_robot_status[rid]["message"] = message


# ─── 화재 대피 ─────────────────────────────────────────────────────────────────

def _get_tracked_pose(robot_ip: str) -> tuple[float, float] | None:
    """WS /tracked_pose로 로봇 실제 현재 좌표 조회"""
    try:
        ws = _create_planning_ws(robot_ip)
        import json as _json
        ws.send(_json.dumps({"enable_topic": "/tracked_pose"}))
        deadline = time.time() + 3.0
        while time.time() < deadline:
            raw = ws.recv()
            if not raw:
                continue
            pkt = _json.loads(raw)
            if pkt.get("topic") == "/tracked_pose":
                pos = pkt.get("pos", [])
                if len(pos) >= 2:
                    ws.close()
                    return float(pos[0]), float(pos[1])
        ws.close()
    except Exception as e:
        logger.warning(f"[Fire/{robot_ip}] tracked_pose 조회 실패: {e}")
    return None


def _determine_safe_side(robot_id: int, robot_ip: str) -> str:
    """로봇 실제 현재 좌표(/tracked_pose) vs 방화벽 선분 cross product → 'L' 또는 'R'
    ORDER BY name으로 FW1→FW2 방향 고정"""
    db = SessionLocal()
    try:
        map_id = _convoy_map_id

        fw_pois = db.query(MapPOI).filter(
            MapPOI.map_id == map_id,
            MapPOI.is_active == True,
            MapPOI.poi_type == "firewall",
        ).order_by(MapPOI.name).limit(2).all()

        if len(fw_pois) >= 2:
            fx1 = float(fw_pois[0].world_x or fw_pois[0].x or 0)
            fy1 = float(fw_pois[0].world_y or fw_pois[0].y or 0)
            fx2 = float(fw_pois[1].world_x or fw_pois[1].x or 0)
            fy2 = float(fw_pois[1].world_y or fw_pois[1].y or 0)

            pos = _get_tracked_pose(robot_ip)
            if pos:
                rx, ry = pos
                cross = (fx2 - fx1) * (ry - fy1) - (fy2 - fy1) * (rx - fx1)
                side = "L" if cross >= 0 else "R"
                logger.info(
                    f"[Fire/Robot {robot_id}] 실제위치({rx:.2f},{ry:.2f}) "
                    f"cross={cross:.3f} → {side}측"
                )
                return side
    except Exception as e:
        logger.warning(f"[Fire/Robot {robot_id}] 사이드 판단 실패: {e}")
    finally:
        db.close()

    # fallback: convoy 투입 순서
    with _convoy_lock:
        ids = [rc["robot_id"] for rc in _convoy_robots]
    n = len(ids)
    idx = ids.index(robot_id) if robot_id in ids else 0
    side = "L" if idx < n / 2 else "R"
    logger.warning(f"[Fire/Robot {robot_id}] fallback 순서({idx}/{n}) → {side}측")
    return side


def _evacuate_robot(rc: dict, side_counter: dict, side_lock: threading.Lock):
    """개별 로봇 대피 스레드"""
    robot_id = rc["robot_id"]
    robot_ip = rc["ip"]

    # 1. 이동 취소
    try:
        cancel_and_verify(robot_ip)
    except Exception as e:
        logger.warning(f"[Fire/Robot {robot_id}] cancel 실패: {e}")
    time.sleep(3.0)

    # 2. SAFE POI 결정
    side = _determine_safe_side(robot_id, robot_ip)
    with side_lock:
        side_counter[side] = side_counter.get(side, 0) + 1
        num = side_counter[side]
    safe_poi_name = f"SAFE-{side}-{num}"

    # 3. SAFE POI 좌표 조회
    db = SessionLocal()
    try:
        safe_poi = db.query(MapPOI).filter(
            MapPOI.name == safe_poi_name,
            MapPOI.is_active == True,
            MapPOI.map_id == _convoy_map_id,
        ).first()
        if not safe_poi:
            logger.error(f"[Fire/Robot {robot_id}] SAFE POI '{safe_poi_name}' 없음")
            _update_robot_status(robot_id, "error", message=f"{safe_poi_name} 없음")
            return
        tx = float(safe_poi.world_x if safe_poi.world_x is not None else safe_poi.x)
        ty = float(safe_poi.world_y if safe_poi.world_y is not None else safe_poi.y)
        t_angle = float(safe_poi.angle or 0.0)
    except Exception as e:
        logger.error(f"[Fire/Robot {robot_id}] POI 조회 실패: {e}")
        return
    finally:
        db.close()

    # 4. 이동
    _update_robot_status(robot_id, "evacuating", current_poi=safe_poi_name,
                         message="대피 장소로 이동 중")
    logger.info(f"[Fire/Robot {robot_id}] 대피 시작: {safe_poi_name} ({tx:.2f}, {ty:.2f})")

    move_lock = _get_move_lock(robot_id)
    stop_event = threading.Event()  # 대피는 외부 중단 없음
    ws = None
    try:
        ws = _create_planning_ws(robot_ip)
    except Exception:
        pass

    ws, result, _ = _execute_move(
        robot_id, robot_ip, tx, ty, t_angle,
        "", ws, move_lock, stop_event, max_retries=2
    )

    if result == "succeeded":
        _update_robot_status(robot_id, "evacuated", current_poi=safe_poi_name)
        logger.info(f"[Fire/Robot {robot_id}] 대피 완료: {safe_poi_name}")
    else:
        logger.error(f"[Fire/Robot {robot_id}] 대피 실패: {result}")
        _update_robot_status(robot_id, "error", message=f"대피 실패({result})")

    if ws:
        try:
            ws.close()
        except Exception:
            pass


def fire_evacuate() -> tuple[bool, str]:
    """화재 경보 수신 → 모든 convoy 로봇 대피 (SAFE-L/R-N으로 이동)"""
    global _convoy_phase

    _fire_event.set()

    with _convoy_lock:
        if _convoy_phase == "idle":
            return False, "convoy가 실행 중이 아닙니다"
        robots = _convoy_robots[:]
        prev_phase = _convoy_phase
        _convoy_phase = "evacuating"

    logger.warning(f"[Fire] 화재 경보 발령 — convoy {len(robots)}대 대피 시작 (이전 phase={prev_phase})")

    # convoy 루프 중단
    if _convoy_stop_event:
        _convoy_stop_event.set()

    # 각 로봇 대피 스레드 실행
    side_counter: dict[str, int] = {}
    side_lock = threading.Lock()
    threads = []
    for rc in robots:
        t = threading.Thread(
            target=_evacuate_robot,
            args=(rc, side_counter, side_lock),
            daemon=True,
        )
        t.start()
        threads.append(t)

    # 모든 대피 완료 후 phase 자동 전환
    def _wait_evacuation_done():
        global _convoy_phase
        for t in threads:
            t.join()
        with _convoy_lock:
            if _convoy_phase == "evacuating":
                _convoy_phase = "evacuated"
                logger.info("[Fire] 모든 로봇 대피 완료 — phase → evacuated")

    threading.Thread(target=_wait_evacuation_done, daemon=True).start()

    log_activity("convoy", "fire_evacuate",
                 f"화재 경보 발령 — convoy {len(robots)}대 SAFE 대피 시작",
                 source="fire_evacuate")
    return True, f"{len(robots)}대 로봇 대피 시작"


def reset_fire() -> None:
    """화재 해제 (상태 초기화)"""
    _fire_event.clear()
    global _convoy_phase
    with _convoy_lock:
        prev = _convoy_phase
        if _convoy_phase == "evacuating":
            _convoy_phase = "stopped"

    log_activity("convoy", "fire_reset",
                 f"화재 해제 — 이전 phase={prev}",
                 source="reset_fire")


def _return_robot_simple(rc: dict):
    """비상정지 후 개별 로봇을 충전소/대기지점으로 복귀 (표준 내비게이션)"""
    robot_id = rc["robot_id"]
    robot_ip = rc["ip"]
    move_lock = _get_move_lock(robot_id)
    stop_event = threading.Event()  # 이 복귀 전용 stop_event
    ws = None

    _update_robot_status(robot_id, "returning", message="복귀 장소로 이동 중")
    with _task_lock:
        _run_info[robot_id] = {"status": "returning", "message": "복귀 장소로 이동 중"}

    try:
        dest_poi = None
        dest_type = None

        db = SessionLocal()
        try:
            robot_row = db.query(Robot).filter(Robot.id == robot_id).first()
            if not robot_row:
                logger.warning(f"[ReturnAll/Robot {robot_id}] DB 로봇 없음")
                return
            logger.info(f"[ReturnAll/Robot {robot_id}] DB 상태: charging_id={robot_row.charging_id}, standby_id={robot_row.standby_id}")

            # convoy_map_id 우선, 없으면 최신 활성 맵 자동 탐지
            map_id = _convoy_map_id
            if not map_id:
                latest_map = db.query(RobotMap).filter(
                    RobotMap.is_active == True
                ).order_by(RobotMap.id.desc()).first()
                if latest_map:
                    map_id = latest_map.id
            if not map_id:
                logger.warning(f"[ReturnAll/Robot {robot_id}] 활성 맵 없음 — 복귀 불가")
                _update_robot_status(robot_id, "error", message="활성 맵 없음")
                return

            # 복귀 목적지 결정 (standby 우선)
            if robot_row.standby_id:
                ref = db.query(MapPOI).filter(MapPOI.id == robot_row.standby_id).first()
                if ref:
                    poi = db.query(MapPOI).filter(
                        MapPOI.name == ref.name, MapPOI.is_active == True,
                        MapPOI.map_id == map_id,
                    ).first()
                    if poi:
                        db.expunge(poi)
                        dest_poi = poi
                        dest_type = "standby"

            if not dest_poi and robot_row.charging_id:
                ref = db.query(MapPOI).filter(MapPOI.id == robot_row.charging_id).first()
                if ref:
                    poi = db.query(MapPOI).filter(
                        MapPOI.name == ref.name, MapPOI.is_active == True,
                        MapPOI.map_id == map_id,
                    ).first()
                    if poi:
                        db.expunge(poi)
                        dest_poi = poi
                        dest_type = "charging"

            if not dest_poi:
                logger.warning(f"[ReturnAll/Robot {robot_id}] 복귀 목적지 없음 (standby_id={robot_row.standby_id}, charging_id={robot_row.charging_id})")
                _update_robot_status(robot_id, "error", message="복귀 목적지 없음")
                return

            # ENTER-LAST 경유 POI 조회
            entry_last = db.query(MapPOI).filter(
                MapPOI.name == "ENTER-LAST", MapPOI.is_active == True,
                MapPOI.map_id == map_id,
            ).first()
            if entry_last:
                db.expunge(entry_last)

            dest_name_1 = f"{dest_poi.name}-1"
            dest_approach = db.query(MapPOI).filter(
                MapPOI.name == dest_name_1, MapPOI.is_active == True,
                MapPOI.map_id == map_id,
            ).first()
            if dest_approach:
                db.expunge(dest_approach)

            waypoints = [p for p in [entry_last, dest_approach] if p]
            all_pois = waypoints + [dest_poi]
            _ensure_world_coords(db, all_pois, robot_id)
        finally:
            db.close()

        # ── 이미 목적지 근처면 이동 생략 ──
        dx = dest_poi.world_x if dest_poi.world_x is not None else dest_poi.x
        dy = dest_poi.world_y if dest_poi.world_y is not None else dest_poi.y
        cur_pos = _get_tracked_pose(robot_ip)
        if cur_pos:
            dist = math.sqrt((cur_pos[0] - float(dx)) ** 2 + (cur_pos[1] - float(dy)) ** 2)
            if dist < 1.0:
                logger.info(f"[ReturnAll/Robot {robot_id}] 이미 목적지({dest_poi.name}) 근처 (dist={dist:.2f}m) — 이동 생략")
                _update_robot_status(robot_id, "standby" if dest_type == "standby" else "charging",
                                     message="이미 목적지에 있음")
                with _task_lock:
                    _run_info[robot_id] = {"status": "standby" if dest_type == "standby" else "charging",
                                           "message": "이미 목적지에 있음"}
                return

        # 기존 이동 취소 후 시작
        logger.info(f"[ReturnAll/Robot {robot_id}] cancel_and_verify 시작")
        cancel_and_verify(robot_ip)
        time.sleep(1.0)
        logger.info(f"[ReturnAll/Robot {robot_id}] WS 생성 → 경유지 {[p.name for p in waypoints]} → 목적지 {dest_poi.name}")

        ws = _create_planning_ws(robot_ip)

        # 최종 목적지 좌표
        tx = dest_poi.world_x if dest_poi.world_x is not None else dest_poi.x
        ty = dest_poi.world_y if dest_poi.world_y is not None else dest_poi.y
        t_angle = dest_poi.angle if dest_poi.angle is not None else 0.0

        # 경유 POI를 route_coords로 묶어서 멈추지 않고 통과
        if waypoints:
            coords_parts = []
            for poi in waypoints:
                px = poi.world_x if poi.world_x is not None else poi.x
                py = poi.world_y if poi.world_y is not None else poi.y
                coords_parts.extend([str(px), str(py)])
            route_coords = ",".join(coords_parts)
            logger.info(f"[ReturnAll/Robot {robot_id}] 경유 {[p.name for p in waypoints]} 통과 → 목적지 {dest_poi.name}")
        else:
            route_coords = ""
            logger.info(f"[ReturnAll/Robot {robot_id}] 직행 → 목적지 {dest_poi.name}")

        if dest_type == "standby":
            ws, result, _ = _execute_move(
                robot_id, robot_ip, tx, ty, t_angle, route_coords,
                ws, move_lock, stop_event)
            while result != "succeeded":
                logger.warning(f"[ReturnAll/Robot {robot_id}] 대기지점 이동 실패 ({result}) — 재시도")
                cancel_and_verify(robot_ip)
                time.sleep(RECOVERY_DELAY)
                try:
                    if ws: ws.close()
                except Exception:
                    pass
                ws = None
                try:
                    ws = _create_planning_ws(robot_ip)
                except Exception:
                    pass
                ws, result, _ = _execute_move(
                    robot_id, robot_ip, tx, ty, t_angle, "",
                    ws, move_lock, stop_event)
            _update_robot_status(robot_id, "standby", message="대기 중")
            with _task_lock:
                _run_info[robot_id] = {"status": "standby", "message": "대기 중"}
        else:
            # 경유점 있으면 먼저 경유 후 충전소 도킹
            if route_coords:
                # dest_approach(C1-1 등)까지 경유점 통과 이동
                last_wp = waypoints[-1] if waypoints else None
                if last_wp:
                    lwx = last_wp.world_x if last_wp.world_x is not None else last_wp.x
                    lwy = last_wp.world_y if last_wp.world_y is not None else last_wp.y
                    lwa = last_wp.angle if last_wp.angle is not None else 0.0
                    # ENTER-LAST만 경유, dest_approach까지 이동
                    enter_coords = route_coords.split(",")
                    if len(enter_coords) > 2:
                        enter_only = ",".join(enter_coords[:2])
                    else:
                        enter_only = route_coords
                    ws, result, _ = _execute_move(
                        robot_id, robot_ip, lwx, lwy, lwa, enter_only,
                        ws, move_lock, stop_event)
                    while result != "succeeded":
                        logger.warning(f"[ReturnAll/Robot {robot_id}] 충전소 경유 실패 ({result}) — 재시도")
                        cancel_and_verify(robot_ip)
                        time.sleep(RECOVERY_DELAY)
                        try:
                            if ws: ws.close()
                        except Exception:
                            pass
                        ws = None
                        try:
                            ws = _create_planning_ws(robot_ip)
                        except Exception:
                            pass
                        ws, result, _ = _execute_move(
                            robot_id, robot_ip, lwx, lwy, lwa, "",
                            ws, move_lock, stop_event)
            time.sleep(1)
            send_charge(robot_ip, charger_name=dest_poi.name)
            _update_robot_status(robot_id, "charging", message="충전 중")
            with _task_lock:
                _run_info[robot_id] = {"status": "charging", "message": "충전 중"}

        logger.info(f"[ReturnAll/Robot {robot_id}] 복귀 완료 ({dest_type}: {dest_poi.name})")

    except Exception as e:
        logger.exception(f"[ReturnAll/Robot {robot_id}] 복귀 예외: {e}")
        _update_robot_status(robot_id, "error", message=str(e))
    finally:
        if ws:
            try:
                ws.close()
            except Exception:
                pass


_return_all_running = threading.Event()  # 중복 호출 방지

def return_all_convoy(interval: float = 15.0) -> tuple[bool, str]:
    """비상정지 후 전체 복귀 — DB에서 활성 로봇 조회 후 1대씩 interval초 간격으로 순차 출발"""
    if _return_all_running.is_set():
        return False, "이미 전체 복귀가 진행 중입니다"
    _return_all_running.set()
    db = SessionLocal()
    try:
        active_robots = db.query(Robot).filter(
            Robot.is_active == True,
            Robot.ip_address.isnot(None),
        ).all()

        robots_info = []
        for r in active_robots:
            if r.ip_address:
                # 오프라인 로봇 제외 (배터리 조회로 온라인 확인)
                pct = _get_battery_percentage(r.ip_address)
                if pct is None:
                    logger.info(f"[ReturnAll] 로봇 {r.id} ({r.ip_address}) 오프라인 — 제외")
                    continue
                robots_info.append({"robot_id": r.id, "ip": r.ip_address})

        # ── 복귀 전 위치 재배치: 배터리 기반으로 중복 없는 위치 배정 ──
        if robots_info:
            map_id = _convoy_map_id
            if not map_id:
                latest_map = db.query(RobotMap).filter(
                    RobotMap.is_active == True
                ).order_by(RobotMap.id.desc()).first()
                if latest_map:
                    map_id = latest_map.id

            if map_id:
                # 임시로 convoy_robots에 전체 로봇 등록 → 재배치 → 원복
                with _convoy_lock:
                    saved_robots = _convoy_robots[:]
                    _convoy_robots[:] = robots_info[:]
                try:
                    _reassign_convoy_positions(map_id=map_id)
                    logger.info(f"[ReturnAll] 복귀 전 위치 재배치 완료 ({len(robots_info)}대)")
                finally:
                    with _convoy_lock:
                        _convoy_robots[:] = saved_robots
    finally:
        db.close()

    if not robots_info:
        _return_all_running.clear()
        return False, "복귀할 로봇이 없습니다 (활성 로봇 없음)"

    # phase를 returning으로 설정 → 프론트 폴링이 "복귀 중" 배너 유지
    global _convoy_phase
    with _convoy_lock:
        _convoy_phase = "returning"

    def _sequential_return():
        try:
            # force_stop의 cancel 스레드가 완전히 종료될 때까지 대기
            time.sleep(15.0)
            logger.info(f"[ReturnAll] 복귀 시작 ({len(robots_info)}대)")
            threads = []
            for i, rc in enumerate(robots_info):
                if i > 0:
                    time.sleep(interval)
                logger.info(f"[ReturnAll] 로봇 {rc['robot_id']} 복귀 출발 ({i + 1}/{len(robots_info)})")
                t = threading.Thread(target=_return_robot_simple, args=(rc,), daemon=True)
                t.start()
                threads.append(t)
            # 전체 복귀 완료 대기
            for t in threads:
                t.join(timeout=300)
            logger.info("[ReturnAll] 전체 복귀 완료")
        finally:
            with _convoy_lock:
                _convoy_phase = "stopped"
            _return_all_running.clear()

    threading.Thread(target=_sequential_return, daemon=True).start()
    log_activity("convoy", "convoy_return_all",
                 f"비상정지 후 전체 복귀 시작 ({len(robots_info)}대, 간격 {interval}초)",
                 source="return_all_convoy")
    return True, f"{len(robots_info)}대 순차 복귀 시작 (간격 {interval}초)"


def _execute_move(
    robot_id: int,
    robot_ip: str,
    tx: float, ty: float, t_angle: float,
    route_coords: str,
    ws,
    move_lock: threading.Lock,
    stop_event: threading.Event,
    max_retries: int = 3,
    target_accuracy: float | None = None,
    cancel_on_stuck: bool = False,
    stuck_delay: float = 1.5,
) -> tuple:
    """이동 실행 + 완료 대기 (재시도 포함)
    cancel_on_stuck: 장애물 감지 시 취소 후 stuck_delay초 대기 → 재시도
    반환: (ws, result, detail)
    """
    result = ""
    detail = ""
    stuck_retries = 0
    # 장애물 무한 재시도 (20회마다 경고 로그)

    for attempt in range(1, max_retries + 1):
        if stop_event.is_set():
            return ws, "cancelled", ""

        with move_lock:
            if attempt > 1:
                cancel_and_verify(robot_ip)
                time.sleep(RECOVERY_DELAY)

                if ws is None:
                    try:
                        ws = _create_planning_ws(robot_ip)
                    except Exception:
                        pass

            ok, move_id, err = send_move(
                robot_ip, tx, ty, t_angle,
                route_coords=route_coords,
                target_accuracy=target_accuracy)
            if not ok:
                logger.error(f"[Robot {robot_id}] 이동 명령 실패: {err}")
                if attempt < max_retries:
                    continue
                return ws, "failed", err

            if ws:
                try:
                    result, detail = _wait_for_move_ws(
                        ws, move_id, robot_ip, stop_event, robot_id=robot_id,
                        cancel_on_stuck=cancel_on_stuck)
                    if result == "ws_error":
                        try:
                            ws.close()
                        except Exception:
                            pass
                        ws = None
                except (WebSocketException, OSError) as e:
                    try:
                        ws.close()
                    except Exception:
                        pass
                    ws = None
                    result = "ws_error"
                    detail = str(e)
            else:
                result, detail = _wait_for_move_http(
                    robot_ip, move_id, stop_event)

        # 장애물 감지 → 대기 후 같은 이동 재시도 (무한 재시도)
        if result == "stuck":
            stuck_retries += 1
            if stuck_retries % 20 == 0:
                logger.warning(f"[Robot {robot_id}] 장애물 {stuck_retries}회 감지 — 계속 재시도 중")
            for _ in range(int(stuck_delay * 10)):
                if stop_event.is_set():
                    return ws, "cancelled", ""
                time.sleep(0.1)
            # WS 재연결 후 같은 attempt로 재시도
            try:
                if ws: ws.close()
            except Exception:
                pass
            ws = None
            try:
                ws = _create_planning_ws(robot_ip)
            except Exception:
                pass
            continue

        if result in ("failed", "ws_error") and attempt < max_retries:
            continue
        break

    return ws, result, detail
