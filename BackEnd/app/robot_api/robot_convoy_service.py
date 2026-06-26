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
from concurrent.futures import ThreadPoolExecutor
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


def _prefetch_convoy_battery() -> None:
    """convoy 멤버 배터리를 _convoy_battery_cache에 병렬로 채워둠.

    `_reassign_convoy_positions`를 `_convoy_hot_swap_lock` 안에서 호출하면
    캐시 미스 시 락 보유 중 외부 WS 호출(N대 × 5초)이 발생함.
    이 함수를 락 잡기 직전에 호출하면 락 안에서는 캐시만 사용하므로 락 보유 시간이 짧아짐.
    """
    with _convoy_lock:
        robots = list(_convoy_robots)
    missing = [rc for rc in robots if rc["robot_id"] not in _convoy_battery_cache]
    if not missing:
        return

    def _probe(rc):
        try:
            return rc["robot_id"], _get_battery_percentage(rc["ip"])
        except Exception:
            return rc["robot_id"], None

    with ThreadPoolExecutor(max_workers=min(len(missing), 8)) as ex:
        for rid, pct in ex.map(_probe, missing):
            if pct is not None:
                _convoy_battery_cache[rid] = pct


def _reassign_convoy_positions(
    map_id: int | None = None,
    excluded_positions: set[str] | None = None,
):
    """전체 convoy 로봇 배터리 조회 → 위치 재배치 (DB 업데이트)
    excluded_positions: hot swap 등으로 이미 점유된 위치 — 재배치 대상에서 제외
    NOTE: 복귀 요청된 로봇(_convoy_return_requested)은 재배치 대상에서 제외 — 이미 충전소 예약됨.
    """
    with _convoy_lock:
        robots = _convoy_robots[:]
        pending_return_set = set(_convoy_return_requested)

    if not robots:
        return

    # 복귀 후보는 재배치 대상에서 제외 (이미 충전소 예약 완료, 자리 충돌 방지)
    if pending_return_set:
        before = [rc["robot_id"] for rc in robots]
        robots = [rc for rc in robots if rc["robot_id"] not in pending_return_set]
        excluded_rids = sorted(pending_return_set)
        logger.info(f"[Convoy 재배치] 복귀 후보 제외: {excluded_rids} (전체: {before})")
        if not robots:
            logger.info("[Convoy 재배치] 모든 대상이 복귀 후보 — 재배치 스킵")
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

        # 배정 안 된 로봇 → 기존 위치 유지 (NULL 클리어 X)
        # 클리어하면 다음 복귀 시 갈 충전소를 잃어버려 운영 이탈 가능 → 기존 charging_id 보존
        # 운영 의도: 모든 컨보이 멤버는 정상적으로 충전소(C1~C3)로 복귀해야 함
        for (rid, pct) in battery_levels:
            if rid not in assigned_rids:
                logger.warning(f"[Convoy 재배치] 로봇 {rid} 배정 위치 없음 — 기존 위치 유지 (clear 안 함)")

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
# 시작/정지 transition을 직렬화 — start와 force_stop이 동시에 들어오는 race 방지
# (별도 락. _convoy_lock과 다름. orchestrator가 _convoy_lock만 사용하므로 데드락 X)
_convoy_transition_lock = threading.Lock()
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
_convoy_return_requested_at: dict[int, float] = {}  # robot_id → 등록 시각(time.time()) — 타임아웃 자동 해제용
_convoy_hourly_timer: Optional[threading.Timer] = None  # 1시간 배터리 체크 타이머
_convoy_hotswap_threads: list[threading.Thread] = []    # hot swap으로 투입된 워커 스레드 목록
_battery_rotation_timer: Optional[threading.Timer] = None  # 대기 배터리 로테이션 타이머
_battery_rotation_stop = threading.Event()  # 로테이션 중지 플래그
_rotating_robots: set[int] = set()  # 현재 로테이션 진행 중인 로봇 ID — 중복 swap thread 생성 방지 (누수 차단)
_rotating_robots_lock = threading.Lock()
_charging_start_time: dict[int, float] = {}  # {robot_id: 충전 시작 시각} — 오래된 순 정렬용
_convoy_map_id: int | None = None                        # 현재 convoy 작업 맵 ID
_fire_event = threading.Event()                           # 화재 경보 이벤트
_convoy_battery_cache: dict[int, float] = {}               # robot_id → 배터리 % 캐시
_convoy_return_events: dict[int, threading.Event] = {}     # robot_id → 개별 복귀 이벤트 (순차 복귀용)
_convoy_all_arrived = threading.Event()                    # 재개 모드: 전원 도착 → 5초 후 작업 시작
_convoy_countdown_until: float | None = None               # 카운트다운 종료 시각 (time.time() 기준)

CONVOY_BATTERY_CHECK_INTERVAL = 300  # 기본 5분(초) — DB convoy_configs.battery_check_interval(분)로 override됨
RETURN_REQUEST_TIMEOUT = 1800        # 복귀 요청 자동 해제 임계값(초) — 30분 내 WORK4 미도달 시 stuck으로 판정
_convoy_flush_timer: Optional[threading.Timer] = None
CONVOY_FLUSH_INTERVAL = 3  # DB 플러시 주기(초)


def _create_convoy_alarm(error_code: str, severity: str, message: str,
                         robot_sn: str | None = None,
                         description: str | None = None):
    """Convoy 백그라운드 스레드에서 알람 로그 생성 (DB 세션 자동 관리)"""
    try:
        from app.crud.alarm_log import create_alarm_log
        from app.schemas.alarm_log import AlarmLogCreate
        db = SessionLocal()
        try:
            create_alarm_log(db, AlarmLogCreate(
                error_code=error_code,
                error_type="task",
                severity=severity,
                message=message,
                description=description,
                source="robot_convoy_service",
                robot_sn=robot_sn,
            ))
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"[Convoy] 알람 로그 생성 실패: {e}")


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
            # 복원된 항목들의 타임스탬프는 알 수 없음 — 현재 시각으로 초기화 (보수적: 다시 30분 카운트)
            _now_ts = time.time()
            _convoy_return_requested_at.clear()
            for _rid in rr:
                _convoy_return_requested_at[int(_rid)] = _now_ts

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

_DOCKING_OFFSET = 0.9  # 충전소에서 도킹 포인트까지의 거리 (m) — relocalize용


def _auto_relocalize_robots(robot_ids: list[int]) -> dict:
    """Convoy 시작 직전 모든 참여 로봇을 자기 충전소/대기지점 좌표로 강제 위치 인식.
    부팅 후 SLAM 위치 어긋남 → 진입 미도착 사이클 차단.

    우선순위: standby_id (대기지점) > charging_id (충전소+0.9m 도킹 오프셋)

    구현:
      1) DB에서 모든 로봇의 좌표/secret 미리 직렬 추출 (빠름)
      2) HTTP set_chassis_pose 호출은 ThreadPoolExecutor로 병렬 (with 블록 → 자동 thread 정리)
      → 모든 로봇 다운인 worst case에도 최대 ~15초 (직렬이면 N×15초)

    반환: {"success": [robot_id...], "failed": [{"robot_id", "reason"}...]}
    """
    from app.routers.robot import ROBOTS  # 로봇 secret 매핑

    success_ids: list[int] = []
    failed: list[dict] = []

    # ── Phase 1: DB에서 작업 정보 미리 추출 (직렬, 빠름 — 같은 세션 재사용) ──
    tasks: list[dict] = []
    db = SessionLocal()
    try:
        for rid in robot_ids:
            robot = db.query(Robot).filter(Robot.id == rid, Robot.is_active == True).first()
            if not robot or not robot.ip_address:
                failed.append({"robot_id": rid, "reason": "로봇 또는 IP 미등록"})
                continue

            # standby 우선, 없으면 charging
            poi = None
            use_docking_offset = False
            if robot.standby_id:
                poi = db.query(MapPOI).filter(
                    MapPOI.id == robot.standby_id, MapPOI.is_active == True
                ).first()
            if not poi and robot.charging_id:
                poi = db.query(MapPOI).filter(
                    MapPOI.id == robot.charging_id, MapPOI.is_active == True
                ).first()
                use_docking_offset = True

            if not poi or poi.world_x is None or poi.world_y is None:
                failed.append({"robot_id": rid, "reason": "POI/좌표 없음"})
                continue

            secret = next((r["secret"] for r in ROBOTS if r["ip"] == robot.ip_address), None)
            if not secret:
                failed.append({"robot_id": rid, "reason": f"등록되지 않은 IP: {robot.ip_address}"})
                continue

            yaw_rad = poi.angle if poi.angle is not None else 0.0
            if use_docking_offset:
                target_x = poi.world_x + _DOCKING_OFFSET * math.cos(yaw_rad)
                target_y = poi.world_y + _DOCKING_OFFSET * math.sin(yaw_rad)
                target_yaw = yaw_rad + math.pi
            else:
                target_x = poi.world_x
                target_y = poi.world_y
                target_yaw = yaw_rad

            tasks.append({
                "robot_id": rid,
                "robot_name": robot.name,
                "ip": robot.ip_address,
                "secret": secret,
                "target_x": target_x,
                "target_y": target_y,
                "target_yaw": target_yaw,
                "poi_name": poi.name,
            })
    finally:
        db.close()

    if not tasks:
        return {"success": success_ids, "failed": failed}

    # ── Phase 2: HTTP 호출 병렬 처리 (with 블록 → ThreadPoolExecutor 자동 정리) ──
    def _relocalize_one(t: dict) -> tuple[dict, bool, str | None]:
        try:
            set_chassis_pose(t["ip"], t["secret"], {
                "position": [t["target_x"], t["target_y"], 0],
                "ori": t["target_yaw"],
            })
            return (t, True, None)
        except Exception as e:
            return (t, False, str(e))

    with ThreadPoolExecutor(
        max_workers=max(1, len(tasks)),
        thread_name_prefix="convoy-relocalize",
    ) as ex:
        results = list(ex.map(_relocalize_one, tasks))

    # 결과 처리 (with 블록 종료 후 → thread pool 이미 정리됨)
    for t, ok, err in results:
        if ok:
            logger.info(
                f"[Convoy auto-relocalize] 로봇 {t['robot_id']} ({t['ip']}) "
                f"→ '{t['poi_name']}' 좌표 인식 완료"
            )
            log_activity(
                "map", "auto_relocalize",
                f"로봇 '{t['robot_name']}' Convoy 시작 자동 위치재조정 → '{t['poi_name']}'",
                robot_id=t["robot_id"], robot_name=t["robot_name"],
                source="_auto_relocalize_robots",
            )
            success_ids.append(t["robot_id"])
        else:
            logger.warning(f"[Convoy auto-relocalize] 로봇 {t['robot_id']} 실패: {err}")
            failed.append({"robot_id": t["robot_id"], "reason": err})

    return {"success": success_ids, "failed": failed}


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

    # 시작/정지 transition을 직렬화 — start 도중 force_stop이 끼어드는 race 방지
    if not _convoy_transition_lock.acquire(timeout=5.0):
        return False, "다른 시작/정지 작업이 진행 중입니다 (5초 timeout) — 잠시 후 다시 시도하세요"

    try:
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
            _convoy_battery_cache.clear()  # stale 배터리 값으로 잘못된 위치 배치 방지
            _convoy_standby_pool = list(standby_robots) if standby_robots else []
            _convoy_work_poi_names = work_poi_names[:]
            _convoy_stop_names = stop_names[:]
            _convoy_return_requested.clear()
            _convoy_return_requested_at.clear()
            _convoy_hotswap_threads.clear()
            _convoy_map_id = None  # 워커 시작 후 work_pois에서 설정됨
            _convoy_return_events = {rc["robot_id"]: threading.Event() for rc in robots_config}
            _convoy_all_arrived.clear()

        # 자동 위치재조정 — 부팅 후 SLAM 위치 어긋남으로 진입 미도착 사이클을 끊기 위함.
        # 모든 참여 로봇(즉시 출발 + 대기 풀)을 자기 충전소/대기지점 좌표로 강제 인식.
        # 전제: 시작 버튼을 누르는 시점에는 모든 로봇이 자기 위치에 물리적으로 있어야 함.
        # NOTE: 상태 초기화(_convoy_stop_event 등)는 위 with 블록에서 이미 완료되어야 함 — 그래야 실패해도 orchestrator가 정상 시작 가능.
        try:
            all_ids = [rc["robot_id"] for rc in robots_config]
            if standby_robots:
                all_ids.extend(rc["robot_id"] for rc in standby_robots)
            relocalize_result = _auto_relocalize_robots(all_ids)
            logger.info(
                f"[Convoy] 자동 위치재조정 완료 — 성공 {len(relocalize_result['success'])}대, "
                f"실패 {len(relocalize_result['failed'])}대"
            )
            # SLAM 안정화 대기 (1.5초) — 위치 인식 후 곧바로 이동 명령 보내면 잘못된 경로 계산 가능
            time.sleep(1.5)
        except Exception as e:
            logger.warning(f"[Convoy] 자동 위치재조정 중 예외 (무시하고 계속): {e}")

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

        # 작업 멤버는 출발과 동시에 충전소/대기지점을 떠나므로 점유를 해제.
        # → standby pool의 W 로봇이 빈 C를 찾을 수 있게 됨.
        # 비상정지 복귀 시에는 return_all_convoy가 _reassign_convoy_positions를 통해 DB를 다시 채움.
        try:
            active_ids = [rc["robot_id"] for rc in robots_config]
            if active_ids:
                _db = SessionLocal()
                try:
                    _db.query(Robot).filter(Robot.id.in_(active_ids)).update(
                        {"charging_id": None, "standby_id": None},
                        synchronize_session=False,
                    )
                    _db.commit()
                    logger.info(f"[Convoy] 작업 멤버 충전소/대기지점 점유 해제: {active_ids}")
                finally:
                    _db.close()
        except Exception as e:
            logger.warning(f"[Convoy] 작업 멤버 점유 해제 실패 (무시하고 계속): {e}")

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
    finally:
        _convoy_transition_lock.release()


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

            ws = None
            free_c_id: int | None = None
            c_name: str | None = None
            tx = ty = t_angle = 0.0

            # 1단계: DB에서 빈 충전소만 조회 후 즉시 close (외부 IO 전에 세션 반환)
            db = SessionLocal()
            try:
                # NOTE: 이전에는 convoy 멤버를 occupied에서 제외했으나,
                # 컨보이 시작 직후에는 멤버가 아직 충전소에서 떠나기 전임.
                # 그 사이 standby 로봇이 같은 C로 이동하면 두 대가 동일 충전소에 배정되는 충돌 발생.
                # → convoy 멤버 여부와 관계없이 charging_id가 있으면 모두 occupied로 처리.
                occupied_ids = set()
                for r in db.query(Robot).filter(
                    Robot.is_active == True, Robot.id != robot_id
                ).all():
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

                if free_c:
                    free_c_id = free_c.id
                    c_name = free_c.name
                    tx = free_c.world_x if free_c.world_x is not None else free_c.x
                    ty = free_c.world_y if free_c.world_y is not None else free_c.y
                    t_angle = free_c.angle if free_c.angle is not None else 0.0
            finally:
                db.close()

            if not c_name:
                logger.info(f"[Standby→C] 로봇 {robot_id} ({start_poi}): 빈 충전소 없음 — 대기 유지")
                continue

            # 2단계: DB 세션 없이 외부 이동 명령 (최대 MOVE_TIMEOUT=30분 가능)
            try:
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
            except Exception as e:
                logger.exception(f"[Standby→C] 로봇 {robot_id} 이동 예외: {e}")
                continue
            finally:
                if ws:
                    try:
                        ws.close()
                    except Exception:
                        pass

            # 3단계: 짧은 새 세션으로 결과만 DB 반영
            db2 = SessionLocal()
            try:
                robot_row = db2.query(Robot).filter(Robot.id == robot_id).first()
                if robot_row:
                    robot_row.standby_id = None
                    robot_row.charging_id = free_c_id
                    db2.commit()
            except Exception as e:
                db2.rollback()
                logger.exception(f"[Standby→C] 로봇 {robot_id} DB 업데이트 실패: {e}")
            finally:
                db2.close()

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
        _convoy_return_requested_at.clear()
        _convoy_hotswap_threads.clear()
        _convoy_map_id = None
        _convoy_return_events = {rc["robot_id"]: threading.Event() for rc in robots_config}
        _convoy_all_arrived.clear()

    # 작업 멤버는 출발과 동시에 충전소/대기지점을 떠나므로 점유를 해제.
    # → standby pool의 W 로봇이 빈 C를 찾을 수 있게 됨.
    # 비상정지 복귀 시에는 return_all_convoy가 _reassign_convoy_positions를 통해 DB를 다시 채움.
    try:
        active_ids = [rc["robot_id"] for rc in robots_config]
        if active_ids:
            _db = SessionLocal()
            try:
                _db.query(Robot).filter(Robot.id.in_(active_ids)).update(
                    {"charging_id": None, "standby_id": None},
                    synchronize_session=False,
                )
                _db.commit()
                logger.info(f"[Convoy] (재개) 작업 멤버 충전소/대기지점 점유 해제: {active_ids}")
            finally:
                _db.close()
    except Exception as e:
        logger.warning(f"[Convoy] (재개) 작업 멤버 점유 해제 실패 (무시하고 계속): {e}")

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
    """로봇 실제 좌표(x, y, orientation) 조회

    NOTE: try/finally로 ws.close() 보장 — 예외 시 socket 누수 방지
    """
    ws = None
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
                    return float(pos[0]), float(pos[1]), float(ori)
    except Exception as e:
        logger.warning(f"[Convoy/{robot_ip}] pose 조회 실패: {e}")
    finally:
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass
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
    """즉시 정지 + 순차 복귀 — 모든 로봇 이동 즉시 취소 → 먼 로봇부터 3초 대기 → 7초 간격 복귀

    NOTE: entering 단계(진입 중)에는 거부함. 모든 로봇이 작업 위치에 도달한 후
    (phase=running) 호출해야 race condition 없이 안전하게 종료 가능.
    비상정지가 필요하면 force_stop_convoy를 사용 (phase 무관하게 항상 동작).
    """
    global _convoy_phase, _convoy_hourly_timer

    with _convoy_lock:
        if _convoy_phase in ("idle", "stopped"):
            return False, "실행 중인 작업이 없습니다"
        if _convoy_phase == "entering":
            return False, "작업 진입 중입니다 — 모든 로봇이 작업 위치에 도달한 후 종료할 수 있습니다 (비상정지는 별도 버튼 사용)"

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
    """즉시 정지 — 모든 로봇 이동 취소 + 상태 리셋

    transition_lock으로 start와 직렬화하여 race 방지.
    비상정지이므로 lock 획득 실패해도 강제 진행.
    """
    global _convoy_phase, _convoy_hourly_timer

    # 시작/정지 transition 직렬화. 실패해도 비상정지는 강제 진행.
    acquired = _convoy_transition_lock.acquire(timeout=5.0)
    if not acquired:
        logger.warning("[force_stop] transition lock 5초 timeout — 강제 진행")

    try:
        # 타이머 취소
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

        # ── race 안전망: 2차 cancel ──
        # 1차 cancel과 워커의 send_move 사이에 race가 있을 수 있음
        # (워커가 stop_event 체크 직후 ~ send_move 발사 사이 1ms~수십ms 갭)
        # 1초 후 한 번 더 cancel 보내서 그 race로 출발한 로봇도 정지시킴
        time.sleep(1.0)
        cancel_threads2 = []
        for rc in robots:
            t = threading.Thread(target=_cancel_robot, args=(rc,), daemon=True)
            t.start()
            cancel_threads2.append(t)
        for t in cancel_threads2:
            t.join(timeout=6.0)
        logger.info("[Convoy] 2차 cancel 완료 (race 안전망)")

        # 로봇 현재 위치를 DB에 저장 (다시 출발용)
        _db = SessionLocal()
        try:
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
    finally:
        if acquired:
            _convoy_transition_lock.release()


def reset_convoy_state() -> tuple[bool, str]:
    """[관리자용] Convoy 상태 강제 초기화

    복귀 중 워커 thread가 hang되거나 도킹 실패로 phase가 'returning' 상태에서
    풀리지 않을 때 강제로 idle 상태로 되돌린다.

    동작:
    1. stop_event/graceful_event 모두 set → 모든 워커 종료 신호
    2. 모든 로봇 이동 cancel (2회, race 안전망)
    3. 타이머 모두 취소
    4. 메모리 state 전면 클리어 (robots, status, positions, standby pool, hotswap threads, return events)
    5. ConvoySavedState DB 테이블 클리어 (재개 정보 폐기 — 다음 시작은 무조건 새로 시작)
    6. phase = "idle"

    NOTE: 일반 종료가 정상 동작할 때는 사용 금지. 이상 상황 전용.
    """
    global _convoy_phase, _convoy_hourly_timer, _battery_rotation_timer
    global _convoy_robots, _convoy_robot_status, _convoy_node_positions
    global _convoy_standby_pool, _convoy_hotswap_threads
    global _convoy_return_events, _convoy_return_requested
    global _convoy_map_id, _convoy_is_resume

    logger.warning("[Convoy] 강제 초기화 요청 — 모든 상태 리셋")

    # 1) 모든 타이머 취소
    if _convoy_hourly_timer:
        try:
            _convoy_hourly_timer.cancel()
        except Exception:
            pass
        _convoy_hourly_timer = None
    if _battery_rotation_timer:
        try:
            _battery_rotation_timer.cancel()
        except Exception:
            pass

    # 2) stop/graceful event 둘 다 set → 모든 워커가 빠져나오도록
    with _convoy_lock:
        robots_snapshot = _convoy_robots[:]
        if _convoy_stop_event:
            _convoy_stop_event.set()
        if _convoy_graceful_event:
            _convoy_graceful_event.set()

    # 3) 모든 로봇 cancel (1차)
    def _cancel_one(rc):
        try:
            cancel_and_verify(rc["ip"])
        except Exception as e:
            logger.warning(f"[Convoy/reset] 로봇 {rc['robot_id']} cancel 실패: {e}")

    cthreads = []
    for rc in robots_snapshot:
        t = threading.Thread(target=_cancel_one, args=(rc,), daemon=True)
        t.start()
        cthreads.append(t)
    for t in cthreads:
        t.join(timeout=6.0)

    # 4) race 안전망 — 1초 후 2차 cancel
    time.sleep(1.0)
    cthreads2 = []
    for rc in robots_snapshot:
        t = threading.Thread(target=_cancel_one, args=(rc,), daemon=True)
        t.start()
        cthreads2.append(t)
    for t in cthreads2:
        t.join(timeout=6.0)

    # 5) 메모리 state 전면 클리어
    with _convoy_lock:
        _convoy_phase = "idle"
        _convoy_is_resume = False
        _convoy_robots = []
        _convoy_robot_status.clear()
        _convoy_node_positions.clear()
        _convoy_standby_pool = []
        _convoy_hotswap_threads.clear()
        _convoy_return_events.clear()
        _convoy_return_requested.clear()
        _convoy_return_requested_at.clear()
        _convoy_battery_cache.clear()
        _convoy_map_id = None
        _fire_event.clear()

    # 6) 태블릿 상태 정리
    with _task_lock:
        for rc in robots_snapshot:
            _confirm_events.pop(rc["robot_id"], None)
            _run_info.pop(rc["robot_id"], None)
            _stuck_states.pop(rc["robot_id"], None)

    # 7) ConvoySavedState DB 클리어 (재개 정보 폐기)
    deleted = 0
    try:
        _db = SessionLocal()
        try:
            deleted = _db.query(ConvoySavedState).delete()
            _db.commit()
        finally:
            _db.close()
    except Exception as e:
        logger.warning(f"[Convoy/reset] ConvoySavedState 클리어 실패: {e}")

    _stop_convoy_flush()
    logger.warning(f"[Convoy] 강제 초기화 완료 (저장상태 {deleted}건 삭제)")
    log_activity("convoy", "convoy_force_reset",
                 f"작업 강제 초기화 — 모든 상태 리셋 (저장상태 {deleted}건 삭제)",
                 source="reset_convoy_state")
    return True, f"작업 상태가 강제 초기화되었습니다 (저장 상태 {deleted}건 삭제)"


def clear_convoy_saved_state() -> tuple[bool, str]:
    """[관리자용] 로봇별 마지막 저장 위치(재개 정보)만 삭제

    컨보이 자체는 정상이지만 다음 시작 시 "재개 모드"가 아니라
    "처음부터 새로 시작"하고 싶을 때 사용한다.

    동작:
    - ConvoySavedState DB 테이블만 클리어
    - 메모리 state, thread, phase 등은 그대로 유지

    NOTE: 실행 중인 컨보이에는 영향 없음. 다음 시작 동작에만 영향.
    """
    # 안전 가드: 작업이 실행 중이면 거부
    with _convoy_lock:
        if _convoy_phase in ("entering", "running", "returning"):
            return False, f"작업이 실행 중입니다 (phase={_convoy_phase}) — 종료 후 시도하세요"

    deleted = 0
    try:
        _db = SessionLocal()
        try:
            deleted = _db.query(ConvoySavedState).delete()
            _db.commit()
        finally:
            _db.close()
    except Exception as e:
        logger.warning(f"[Convoy] 저장 위치 삭제 실패: {e}")
        return False, f"저장 위치 삭제 중 오류 발생: {e}"

    logger.info(f"[Convoy] 저장 위치 삭제 완료 ({deleted}건)")
    log_activity("convoy", "convoy_clear_saved_state",
                 f"작업 저장 위치 삭제 — {deleted}건",
                 source="clear_convoy_saved_state")
    return True, f"저장된 로봇 위치 {deleted}건이 삭제되었습니다 (다음 시작은 새로 시작됩니다)"


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
        # 종료된 thread는 정리 후 새 thread 추가 (장기 운영 시 dead thread 누적 방지)
        _convoy_hotswap_threads[:] = [ht for ht in _convoy_hotswap_threads if ht.is_alive()]
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

    # 1) 만료된 복귀 요청 자동 해제 (30분 내 WORK4 미도달 시 stuck 판정)
    now_ts = time.time()
    expired_robots: list[tuple[int, float]] = []   # (robot_id, elapsed_sec)
    with _convoy_lock:
        for rid, ts in list(_convoy_return_requested_at.items()):
            elapsed = now_ts - ts
            if elapsed > RETURN_REQUEST_TIMEOUT:
                expired_robots.append((rid, elapsed))
                _convoy_return_requested.discard(rid)
                _convoy_return_requested_at.pop(rid, None)

    # 만료된 등록이 있으면 알람 + 활동 로그 기록 (락 외부에서 — DB 접근)
    for rid, elapsed in expired_robots:
        elapsed_min = int(elapsed // 60)
        # 로봇 SN 조회
        robot_sn = None
        robot_name = f"로봇 {rid}"
        try:
            _db = SessionLocal()
            try:
                _r = _db.query(Robot).filter(Robot.id == rid).first()
                if _r:
                    robot_sn = _r.serial_number
                    robot_name = _r.name
            finally:
                _db.close()
        except Exception:
            pass

        msg = f"로봇 '{robot_name}' 복귀 요청 후 {elapsed_min}분 내 WORK4 미도달 — 자동 해제"
        logger.warning(f"[Convoy 시간 체크] {msg}")
        _create_convoy_alarm(
            error_code="CONVOY-RETURN-TIMEOUT",
            severity="warning",
            message=msg,
            robot_sn=robot_sn,
            description=f"_convoy_hourly_battery_check() — {RETURN_REQUEST_TIMEOUT//60}분 타임아웃 자동 해제",
        )
        log_activity("convoy", "return_request_expired",
                     msg, robot_id=rid, robot_name=robot_name,
                     source="_convoy_hourly_battery_check")

    # 2) 만료 처리 후에도 복귀 대기 중인 로봇이 남아 있으면 새 후보 추가 안 함 (중복 등록 방지)
    with _convoy_lock:
        if _convoy_phase != "running":
            return
        robots = _convoy_robots[:]
        pending_return = sorted(_convoy_return_requested)

    if pending_return:
        logger.info(
            f"[Convoy 시간 체크] 이미 복귀 대기 중: {pending_return} — 이번 사이클 스킵"
        )
        _schedule_hourly_check(stop_event)
        return

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

    # 대기 풀 최고 배터리 - convoy 최저 배터리 < 마진 → 교체 스킵
    # (3% 이상 차이 나야 교체 — 근소한 차이로는 이동 비용 대비 이득 없음)
    BATTERY_SWAP_MARGIN = 3.0
    if pool_best_pct < min_pct + BATTERY_SWAP_MARGIN:
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

    # 복귀 요청 등록 + 타임스탬프 (30분 내 미처리 시 자동 해제용)
    with _convoy_lock:
        _convoy_return_requested.add(min_robot_id)
        _convoy_return_requested_at[min_robot_id] = time.time()

    # 복귀 로봇에게 충전소 먼저 예약 (C1 우선)
    # NOTE: try/finally로 _db.close() 보장 — DB 일시 장애 시 세션 누수 방지
    _reserved_charging = None
    _db = SessionLocal()
    try:
        occupied_poi_ids = set()
        for r in _db.query(Robot).filter(Robot.is_active == True, Robot.id != min_robot_id).all():
            if r.charging_id:
                occupied_poi_ids.add(r.charging_id)
        cur_map_id = _convoy_map_id
        robot_row = _db.query(Robot).filter(Robot.id == min_robot_id).first()
        if cur_map_id and robot_row:
            for cname in ["C1", "C2", "C3"]:
                cpoi = _db.query(MapPOI).filter(
                    MapPOI.name == cname, MapPOI.is_active == True,
                    MapPOI.map_id == cur_map_id,
                ).first()
                if cpoi and cpoi.id not in occupied_poi_ids:
                    # 복귀 로봇에게 충전소 배정
                    robot_row.charging_id = cpoi.id
                    robot_row.standby_id = None
                    _db.commit()
                    _reserved_charging = cname
                    logger.info(f"[Convoy 시간 체크] 복귀 로봇 {min_robot_id} → {cname} 예약")
                    break

            # 빈 C 못 찾았으면 기존 charging_id 유지 + standby_id 클리어
            # (워커 복귀 로직이 charging 우선으로 동작하도록 보장)
            if _reserved_charging is None:
                if robot_row.standby_id is not None:
                    robot_row.standby_id = None
                    _db.commit()
                    logger.warning(
                        f"[Convoy 시간 체크] 로봇 {min_robot_id} 빈 충전소 없음 — "
                        f"standby_id 클리어 (워커가 charging_id={robot_row.charging_id}로 복귀)"
                    )
    except Exception as e:
        logger.warning(f"[Convoy 시간 체크] 충전소 예약 실패: {e}")
    finally:
        _db.close()

    # 배터리 기반 위치 재배치 (복귀 로봇 충전소 제외)
    # 락 잡기 전에 배터리 prefetch (락 안에서 외부 WS 호출 차단)
    _prefetch_convoy_battery()
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
                # FIX: 여기서 _schedule_battery_rotation() 호출 제거
                # finally 블록에서 어차피 호출됨 → 이중 호출 시 Timer 누수 (기하급수 폭증)
                return

        # 1단계: DB 메타만 짧게 조회하고 close
        db = SessionLocal()
        try:
            active_robots = db.query(Robot).filter(
                Robot.is_active == True,
                Robot.ip_address.isnot(None),
            ).all()

            charging_robots = []
            standby_robots = []
            max_battery_map: dict[int, int] = {}

            for r in active_robots:
                if not r.ip_address:
                    continue
                max_battery_map[r.id] = r.max_battery or 95

                if r.charging_id:
                    cpoi = db.query(MapPOI).filter(MapPOI.id == r.charging_id).first()
                    if cpoi and cpoi.name in ("C1", "C2", "C3"):
                        charging_robots.append({
                            "id": r.id, "ip": r.ip_address,
                            "max_battery": r.max_battery or 95,
                            "poi_name": cpoi.name, "charging_id": r.charging_id,
                        })
                if r.standby_id:
                    spoi = db.query(MapPOI).filter(MapPOI.id == r.standby_id).first()
                    if spoi and spoi.name in ("W1", "W2"):
                        standby_robots.append({
                            "id": r.id, "ip": r.ip_address,
                            "poi_name": spoi.name, "standby_id": r.standby_id,
                        })
        finally:
            db.close()

        if not charging_robots or not standby_robots:
            # FIX: 여기서 _schedule 호출 제거 — finally가 어차피 호출 (이중 호출 방지)
            return

        # 2단계: DB 세션 없이 N대 배터리 조회 (각 호출 5초+ 가능)
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
                if cr["id"] not in _charging_start_time:
                    _charging_start_time[cr["id"]] = time.time()

        if not fully_charged:
            _schedule_battery_rotation()
            return

        fully_charged.sort(key=lambda x: x["charge_start"])

        for wr in standby_robots:
            w_pct = _get_battery_percentage(wr["ip"])
            wr["battery"] = w_pct if w_pct is not None else 100.0

        standby_robots.sort(key=lambda x: x["battery"])

        swap_count = min(len(fully_charged), len(standby_robots))
        logger.info(f"[Battery Rotation] 완충 {len(fully_charged)}대, 대기 {len(standby_robots)}대 → {swap_count}번 교체")

        # 3단계: 짧은 새 세션으로 교체 결정 + commit
        swap_pairs: list[tuple[dict, dict]] = []
        db2 = SessionLocal()
        try:
            for i in range(swap_count):
                c_robot = fully_charged[i]
                w_robot = standby_robots[i]

                c_row = db2.query(Robot).filter(Robot.id == c_robot["id"]).first()
                w_row = db2.query(Robot).filter(Robot.id == w_robot["id"]).first()
                if not c_row or not w_row:
                    continue

                w_max = w_row.max_battery or 95
                if w_robot["battery"] >= w_max:
                    logger.info(f"[Battery Rotation] 스킵: W 로봇 {w_robot['id']}({w_robot['battery']:.0f}%) >= "
                                f"max({w_max}%) — 이미 충전 충분")
                    continue
                if w_robot["battery"] >= c_robot["battery"]:
                    logger.info(f"[Battery Rotation] 스킵: W 로봇 {w_robot['id']}({w_robot['battery']:.0f}%) >= "
                                f"C 로봇 {c_robot['id']}({c_robot['battery']:.0f}%)")
                    continue

                # 이미 로테이션 진행 중인 로봇은 스킵 (thread 누수 차단)
                with _rotating_robots_lock:
                    if c_robot["id"] in _rotating_robots or w_robot["id"] in _rotating_robots:
                        logger.info(f"[Battery Rotation] 스킵: 로봇 {c_robot['id']} 또는 {w_robot['id']} 이미 진행 중")
                        continue

                c_row.charging_id = None
                c_row.standby_id = w_robot["standby_id"]
                w_row.standby_id = None
                w_row.charging_id = c_robot["charging_id"]
                swap_pairs.append((c_robot, w_robot))

            if swap_pairs:
                db2.commit()
        except Exception as e:
            db2.rollback()
            logger.warning(f"[Battery Rotation] DB 교환 실패: {e}")
            swap_pairs = []
        finally:
            db2.close()

        # 4단계: DB 세션 없이 실제 이동 thread 시작
        for c_robot, w_robot in swap_pairs:
            logger.info(f"[Battery Rotation] 로봇 {c_robot['id']}({c_robot['poi_name']}) ↔ "
                        f"로봇 {w_robot['id']}({w_robot['poi_name']})")
            _charging_start_time.pop(c_robot["id"], None)
            _charging_start_time[w_robot["id"]] = time.time()
            # 진행 중 등록 (thread 종료 시 _rotate_swap_sequential의 finally에서 해제)
            with _rotating_robots_lock:
                _rotating_robots.add(c_robot["id"])
                _rotating_robots.add(w_robot["id"])
            threading.Thread(
                target=_rotate_swap_sequential,
                args=(
                    w_robot["id"], w_robot["ip"], c_robot["poi_name"],
                    c_robot["id"], c_robot["ip"], w_robot["poi_name"],
                ),
                daemon=True,
            ).start()
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

    NOTE: 죽은 로봇이 끼어 영원히 안 끝나는 것을 방지하기 위해 join에 timeout 부여.
    각 로봇은 _rotate_robot_move 자체에서 max_retries로 보호됨.
    """
    # 정상 로테이션은 1분 내 끝남. 5분이면 안전 마진 충분.
    # (이전 3600초 → 죽은 로봇 1대 끼면 thread 2시간 점유 → 누수 원인)
    JOIN_TIMEOUT = 300.0
    try:
        logger.info(f"[Battery Rotation] 동시 출발: 로봇 {w_id}({w_poi_name} → {c_poi_name}), "
                     f"로봇 {c_id}({c_poi_name} → {w_poi_name})")
        t1 = threading.Thread(target=_rotate_robot_move, args=(w_id, w_ip, c_poi_name, "charging"), daemon=True)
        t2 = threading.Thread(target=_rotate_robot_move, args=(c_id, c_ip, w_poi_name, "standby"), daemon=True)
        t1.start()
        t2.start()
        t1.join(timeout=JOIN_TIMEOUT)
        t2.join(timeout=JOIN_TIMEOUT)
        if t1.is_alive() or t2.is_alive():
            logger.warning(f"[Battery Rotation] 교체 timeout ({JOIN_TIMEOUT}s) — 로봇 {w_id}/{c_id} 진행 중일 수 있음")
        else:
            logger.info(f"[Battery Rotation] 교체 완료: 로봇 {w_id} ↔ 로봇 {c_id}")
    except Exception as e:
        logger.warning(f"[Battery Rotation] 동시 교체 실패: {e}")
    finally:
        # 진행 중 등록 해제 — 다음 사이클에서 같은 로봇 swap 가능하도록
        with _rotating_robots_lock:
            _rotating_robots.discard(w_id)
            _rotating_robots.discard(c_id)


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
        # 죽은 로봇이 끼어 영원히 재시도하는 것을 막기 위한 한도
        MAX_RETRIES = 5
        while result != "succeeded" and retry_count < MAX_RETRIES:
            retry_count += 1
            logger.warning(f"[Rotate Robot {robot_id}] 이동 실패 ({result}) — 재시도 {retry_count}/{MAX_RETRIES}")
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

        if result != "succeeded":
            logger.error(f"[Rotate Robot {robot_id}] 최대 재시도({MAX_RETRIES}) 도달 — 포기 ({result})")
            return

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
    """배터리 로테이션 타이머 예약 (3분 간격)

    NOTE: 옛 Timer가 살아있으면 반드시 cancel.
    이전에 cancel 누락 + _battery_rotation_check의 이중 호출(if 분기 + finally)로
    매 3분 trigger마다 Timer가 기하급수적으로 누수됨 (1→2→4→8→16→32→64...).
    18분만에 64개 살아있는 Timer 누적 확인됨.
    """
    global _battery_rotation_timer
    if _battery_rotation_stop.is_set():
        return
    # FIX: 옛 Timer cancel — Timer 누수 방지
    if _battery_rotation_timer is not None:
        try:
            _battery_rotation_timer.cancel()
        except Exception:
            pass
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

    # 배터리 부족 복귀 시 신규 투입을 ENTER-LAST 통과 시점에 트리거하기 위한 가드.
    # watch 스레드와 워커 도킹 후 트리거 양쪽에서 set 검사.
    standby_triggered = threading.Event()

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

        # current_node fallback — 진입 전에 graceful_event 발동 시 UnboundLocalError 방지
        # (한 번 발생한 사건: 2026-04-29 07:47:07, line 2623)
        current_node = 0
        loop_count = 0

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
                                    # cancel_on_stuck 제거 (2026-04-29) — chassis 자체 회복(장애물 사라지면 자동 출발) 보존
                                    # 4월 24일 이전 동작 복원: backend가 stuck 처리에 끼어들지 않음
                                    ws, result, detail = _execute_move(
                                        robot_id, robot_ip, tx, ty, t_angle, route_coords,
                                        ws, move_lock, stop_event, target_accuracy=0.03)
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
                            _convoy_return_requested_at.pop(robot_id, None)
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
                            _convoy_return_requested_at.pop(robot_id, None)
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
                    # [무한 루프 방지] event clear — 다음 segment에서 재감지되어 무한 outer retry되는 사고 차단
                    confirm_event.clear()
                    break

                # cancel_on_stuck 제거 (2026-04-29) — chassis 자체 회복 보존
                # 장애물 감지 시 chassis가 자체적으로 멈춤 → 장애물 사라지면 자동 출발
                # 4월 24일 이전 동작 복원
                ws, result, detail = _execute_move(
                    robot_id, robot_ip, tx, ty, t_angle, route_coords,
                    ws, move_lock, stop_event, target_accuracy=stop_accuracy)

                if stop_event.is_set() or graceful_event.is_set():
                    break
                # Fix B (2026-04-29) — 확인 버튼이 _execute_move 도중에 눌렸으면 즉시 강제 도착 처리
                # 멈춤 발생 시 사용자가 화면에서 강제로 풀 수 있는 안전망
                if confirm_event and confirm_event.is_set():
                    logger.info(f"[{robot_display}] 확인 버튼 눌림 (이동 중) — 강제 도착 처리")
                    try:
                        cancel_and_verify(robot_ip)
                    except Exception:
                        pass
                    _arrived = True
                    # [무한 루프 방지] event clear — 다음 segment에서 재감지되어 무한 outer retry되는 사고 차단
                    confirm_event.clear()
                    break
                if result == "cancelled":
                    # 사용자 정지가 아니면 stuck/장애물로 인한 자동 cancel.
                    # 워커를 종료하지 말고 cancel_and_verify + ws 재생성 후 재시도.
                    logger.warning(f"[{robot_display}] 이동 자동 cancel (장애물/stuck 감지) — 재시도")
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
                    continue  # while not _arrived 처음으로 — 같은 destination으로 재이동

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
                            # Fix B 안전망: 미도착인데 사용자가 확인 버튼 눌렀으면 강제 도착 처리
                            if confirm_event and confirm_event.is_set():
                                logger.info(f"[{robot_display}] 확인 버튼 눌림 (미도착 거리={dist:.2f}m) — 강제 도착 처리")
                                _arrived = True
                                # [무한 루프 방지] event clear — 다음 segment에서 재감지되어 무한 outer retry되는 사고 차단
                                confirm_event.clear()
                                break
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
            if result == "cancelled" and not _arrived:
                # inner에서 재시도 처리됐어야 하지만 안전망:
                # 사용자/그레이스풀 정지가 아닌데 cancelled로 빠져나온 경우
                # 워커 종료 대신 outer 루프 재시도 (segment 재계산 + 재이동)
                # NOTE: _arrived=True (확인 버튼으로 강제 도착)인 경우는 retry 안 함 — 무한 루프 방지
                logger.warning(f"[{robot_display}] 외부 cancelled 감지 (정지 신호 아님) — outer 재시도")
                continue

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

                    # 배터리 부족 복귀 or 1시간 체크로 복귀 요청된 로봇 → 반드시 충전소
                    # 그레이스풀 복귀(작업 종료) → standby 우선
                    with _convoy_lock:
                        is_return_requested = robot_id in _convoy_return_requested
                    use_charging_first = low_battery_break or is_return_requested
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

                # ── 배터리 복귀 시 충전소 접근점(예: C1-1) 도착 감지 → 신규 투입 ──
                # 신규 로봇의 entry path도 ENTER-LAST를 통과하므로 ENTER-LAST 부근에서
                # 트리거하면 양 로봇이 ENTER-LAST에서 마주칠 수 있음.
                # → 복귀 로봇이 C1-1(충전소 접근점)에 도달했다는 건 이미 ENTER-LAST를 벗어나
                #   충전소 분기로 들어선 상태. 신규 로봇이 ENTER-LAST 통과해도 안전.
                # 도킹 polling + 5초 마진은 생략하므로 약 30~60초 단축됨.
                if low_battery_break and _cur_charging_poi is not None:
                    approach_name = f"{_cur_charging_poi.name}-1"
                    approach_poi = next(
                        (p for p in _cur_return_pois if p.name == approach_name), None
                    )
                    if approach_poi is not None and approach_poi.world_x is not None:
                        ax = float(approach_poi.world_x)
                        ay = float(approach_poi.world_y)

                        def _watch_charging_approach():
                            ARRIVAL_RADIUS = 1.0  # 1m 이내면 접근점 도달 판단
                            POLL_INTERVAL = 1.0
                            WATCH_TIMEOUT = 600.0  # 10분 — 못 가도 종료
                            wait_start = time.time()
                            while time.time() - wait_start < WATCH_TIMEOUT:
                                if (stop_event.is_set() or graceful_event.is_set()
                                        or standby_triggered.is_set()):
                                    return
                                pose = _get_robot_pose(robot_ip)
                                if pose:
                                    dx = pose[0] - ax
                                    dy = pose[1] - ay
                                    if (dx * dx + dy * dy) ** 0.5 < ARRIVAL_RADIUS:
                                        if standby_triggered.is_set():
                                            return
                                        standby_triggered.set()
                                        logger.info(
                                            f"[{robot_display}] {approach_name} 도달 감지 "
                                            f"— 신규 대기 로봇 즉시 투입 (충전소 분기 진입 완료)"
                                        )
                                        try:
                                            _trigger_standby_robot()
                                        except Exception as e:
                                            logger.warning(
                                                f"[{robot_display}] {approach_name} 도달 시점 "
                                                f"_trigger_standby_robot 실패: {e}"
                                            )
                                        return
                                time.sleep(POLL_INTERVAL)

                        threading.Thread(
                            target=_watch_charging_approach,
                            daemon=True,
                            name=f"charging-approach-watch-{robot_id}",
                        ).start()

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
                # send_charge는 도킹 "명령"만 보내고 물리 도킹 완료를 기다리지 않음.
                # 복귀 로봇이 충전소 물리 위치에 도착하기 전에 신규 로봇이 출발하면
                # ENTER-LAST 부근에서 마주치는 사고가 발생함.
                # → 충전소 POI 좌표 도달을 polling으로 확인 후 신규 투입.
                if _cur_charging_poi is not None and _cur_charging_poi.world_x is not None:
                    target_x = float(_cur_charging_poi.world_x)
                    target_y = float(_cur_charging_poi.world_y)
                    ARRIVAL_RADIUS = 0.3   # 30cm 이내 도달 시 도착 판단
                    DOCKING_TIMEOUT = 60.0  # 최대 대기 (도킹 평균 30~60초)
                    POLL_INTERVAL = 2.0

                    wait_start = time.time()
                    docked = False
                    while time.time() - wait_start < DOCKING_TIMEOUT:
                        if stop_event.is_set() or graceful_event.is_set():
                            break
                        pose = _get_robot_pose(robot_ip)
                        if pose:
                            dx = pose[0] - target_x
                            dy = pose[1] - target_y
                            if (dx * dx + dy * dy) ** 0.5 < ARRIVAL_RADIUS:
                                docked = True
                                logger.info(
                                    f"[{robot_display}] 도킹 위치 도착 확인 "
                                    f"(target={_cur_charging_poi.name})"
                                )
                                break
                        time.sleep(POLL_INTERVAL)

                    if not docked and not stop_event.is_set():
                        logger.warning(
                            f"[{robot_display}] 도킹 확인 timeout({DOCKING_TIMEOUT}s) — "
                            "그래도 신규 투입 진행"
                        )

                    # 도킹 모터/충전 단자 접속 안전 마진 (5초)
                    if not stop_event.is_set() and not graceful_event.is_set():
                        time.sleep(5.0)

                if stop_event.is_set() or graceful_event.is_set():
                    logger.info(f"[{robot_display}] 정지 신호 감지 — 신규 투입 취소")
                elif standby_triggered.is_set():
                    # 충전소 접근점 도달 watch가 이미 호출함 — 중복 방지
                    logger.info(f"[{robot_display}] 복귀 완료 (신규 투입은 접근점 도달 시 이미 트리거됨)")
                else:
                    # 1) 대기 풀에서 교체 로봇 투입 (자신이 아닌 다른 로봇)
                    standby_triggered.set()
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
    """WS /tracked_pose로 로봇 실제 현재 좌표 조회

    NOTE: try/finally로 ws.close() 보장 — 예외 시 socket 누수 방지
    """
    ws = None
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
                    return float(pos[0]), float(pos[1])
    except Exception as e:
        logger.warning(f"[Fire/{robot_ip}] tracked_pose 조회 실패: {e}")
    finally:
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass
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

        # 죽은 로봇이 끼어 영원히 재시도하는 것을 막기 위한 한도
        RETURN_MAX_RETRIES = 5

        if dest_type == "standby":
            ws, result, _ = _execute_move(
                robot_id, robot_ip, tx, ty, t_angle, route_coords,
                ws, move_lock, stop_event)
            retry_count = 0
            while result != "succeeded" and retry_count < RETURN_MAX_RETRIES:
                retry_count += 1
                logger.warning(f"[ReturnAll/Robot {robot_id}] 대기지점 이동 실패 ({result}) — 재시도 {retry_count}/{RETURN_MAX_RETRIES}")
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

            if result != "succeeded":
                logger.error(f"[ReturnAll/Robot {robot_id}] 최대 재시도({RETURN_MAX_RETRIES}) 도달 — 포기 ({result})")
                _update_robot_status(robot_id, "error", message=f"대기지점 복귀 실패 ({result})")
                return

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
                    retry_count = 0
                    while result != "succeeded" and retry_count < RETURN_MAX_RETRIES:
                        retry_count += 1
                        logger.warning(f"[ReturnAll/Robot {robot_id}] 충전소 경유 실패 ({result}) — 재시도 {retry_count}/{RETURN_MAX_RETRIES}")
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

                    if result != "succeeded":
                        logger.error(f"[ReturnAll/Robot {robot_id}] 충전소 경유 최대 재시도({RETURN_MAX_RETRIES}) 도달 — 포기 ({result})")
                        _update_robot_status(robot_id, "error", message=f"충전소 경유 실패 ({result})")
                        return
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

    # 1단계: DB에서 활성 로봇 (id, ip)와 map_id 짧게 조회 후 close
    candidates: list[tuple[int, str]] = []
    map_id = _convoy_map_id
    db = SessionLocal()
    try:
        active_robots = db.query(Robot).filter(
            Robot.is_active == True,
            Robot.ip_address.isnot(None),
        ).all()
        for r in active_robots:
            if r.ip_address:
                candidates.append((r.id, r.ip_address))

        if not map_id:
            latest_map = db.query(RobotMap).filter(
                RobotMap.is_active == True
            ).order_by(RobotMap.id.desc()).first()
            if latest_map:
                map_id = latest_map.id
    finally:
        db.close()

    # 2단계: DB 세션 없이 N대 배터리 병렬 조회 (꺼진 로봇이 있어도 직렬 30초+ 대기 회피)
    robots_info: list[dict] = []
    if candidates:
        def _probe(item: tuple[int, str]) -> tuple[int, str, Optional[float]]:
            rid, ip = item
            try:
                pct = _get_battery_percentage(ip)
            except Exception:
                pct = None
            return rid, ip, pct

        with ThreadPoolExecutor(max_workers=min(len(candidates), 8)) as ex:
            for rid, ip, pct in ex.map(_probe, candidates):
                if pct is None:
                    logger.info(f"[ReturnAll] 로봇 {rid} ({ip}) 오프라인 — 제외")
                    continue
                robots_info.append({"robot_id": rid, "ip": ip})

    # 3단계: 위치 재배치 (DB 세션은 _reassign_convoy_positions 내부에서 자체 관리)
    if robots_info and map_id:
        with _convoy_lock:
            saved_robots = _convoy_robots[:]
            _convoy_robots[:] = robots_info[:]
        try:
            _reassign_convoy_positions(map_id=map_id)
            logger.info(f"[ReturnAll] 복귀 전 위치 재배치 완료 ({len(robots_info)}대)")
        finally:
            with _convoy_lock:
                _convoy_robots[:] = saved_robots

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

            # race condition 보호: send_move 직전 stop_event 한 번 더 체크
            # (force_stop이 cancel + stop_event.set 직후 워커가 send_move 하는 race 방지)
            if stop_event.is_set():
                return ws, "cancelled", ""

            ok, move_id, err = send_move(
                robot_ip, tx, ty, t_angle,
                route_coords=route_coords,
                target_accuracy=target_accuracy)

            # send_move 직후도 체크 — 명령 보낸 직후 stop이면 즉시 cancel하여 로봇 정지
            if ok and stop_event.is_set():
                try:
                    cancel_and_verify(robot_ip)
                except Exception as _ce:
                    logger.warning(f"[Robot {robot_id}] race-cancel 실패: {_ce}")
                return ws, "cancelled", ""

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
