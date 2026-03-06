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
from app.models.map import MapPOI, RobotMap
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
    _get_session,
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
        logger.info(
            f"[Robot {robot_id}] POI '{poi.name}' SVG→World: "
            f"({poi.x:.1f},{poi.y:.1f}) → ({poi.world_x:.3f},{poi.world_y:.3f})"
        )


# ─── 배터리 기반 위치 재배치 ──────────────────────────────────────────────────

# 위치 우선순위: 배터리 가장 적은 → C3, 다음 → C2, 다음 → C1, 가장 많은 → W1
_POSITION_ORDER = ["C3", "C2", "C1", "W1"]


def _reassign_convoy_positions():
    """전체 convoy 로봇 배터리 조회 → 위치 재배치 (DB 업데이트)
    가장 낮은 배터리 → C3, 그 다음 → C2 → C1, 최고 → W1
    """
    with _convoy_lock:
        robots = _convoy_robots[:]

    if not robots:
        return

    # 배터리 조회
    battery_levels = []
    for rc in robots:
        pct = _get_battery_percentage(rc["ip"])
        battery_levels.append((rc["robot_id"], pct if pct is not None else 100))
        logger.info(f"[Convoy 재배치] 로봇 {rc['robot_id']} 배터리: {pct}")

    # 배터리 오름차순 정렬 (낮은 것부터 충전소 배정)
    battery_levels.sort(key=lambda x: x[1])

    positions = _POSITION_ORDER[:len(battery_levels)]

    db = SessionLocal()
    try:
        for (rid, pct), pos_name in zip(battery_levels, positions):
            robot = db.query(Robot).filter(Robot.id == rid).first()
            if not robot:
                continue

            poi = db.query(MapPOI).filter(
                MapPOI.name == pos_name, MapPOI.is_active == True
            ).first()
            if not poi:
                logger.warning(f"[Convoy 재배치] POI '{pos_name}' 없음")
                continue

            if pos_name.startswith("W"):
                robot.standby_id = poi.id
                robot.charging_id = None
            else:
                robot.charging_id = poi.id
                robot.standby_id = None

            logger.info(f"[Convoy 재배치] 로봇 {rid} ({pct:.0f}%) → {pos_name}")

        db.commit()
        reassign_desc = ", ".join(f"로봇{rid}({pct:.0f}%)→{pos}" for (rid, pct), pos in zip(battery_levels, positions))
        logger.info("[Convoy 재배치] DB 업데이트 완료")
        log_activity("convoy", "convoy_reassign",
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
_convoy_stop_event: Optional[threading.Event] = None
_convoy_graceful_event: Optional[threading.Event] = None
_convoy_robots: list[dict] = []  # [{robot_id, ip, entry_names, return_names, ...}]
_convoy_robot_status: dict[int, dict] = {}  # {robot_id: {status, current_poi, loop, ...}}
_convoy_at_stop: dict[int, int | None] = {}  # {robot_id: 정지점 노드 인덱스 or None(이동 중)}


# ─── Convoy 상태 조회 ──────────────────────────────────────────────────────────

def get_convoy_status() -> dict:
    """convoy 전체 상태 + 개별 로봇 상태 반환"""
    with _convoy_lock:
        robots = []
        for rc in _convoy_robots:
            rid = rc["robot_id"]
            rs = _convoy_robot_status.get(rid, {"status": "idle"})
            at_stop = _convoy_at_stop.get(rid)
            robots.append({"robot_id": rid, "at_stop": at_stop, **rs})
        return {
            "phase": _convoy_phase,
            "robots": robots,
        }


# ─── Convoy 시작 ───────────────────────────────────────────────────────────────

def start_convoy(
    robots_config: list[dict],
    work_poi_names: list[str],
    stop_names: list[str],
) -> tuple[bool, str]:
    """Convoy 대열 작업 시작

    robots_config: [
      { "robot_id": 9, "ip": "192.168.0.31",
        "entry_poi_names": ["ENTER3-1","ENTER-LAST"],
        "return_poi_names": ["ENTER-LAST","ENTER3-1"] },
      ...
    ]
    work_poi_names: ["WORK1","WORK2","WORK3","WORK4","WORK5","WORK6"]
    stop_names: ["WORK2","WORK4"]

    robots_config 순서 = 출발 순서 (C1→C2→C3)
    """
    global _convoy_phase, _convoy_stop_event, _convoy_graceful_event
    global _convoy_robots, _convoy_robot_status, _convoy_at_stop

    with _convoy_lock:
        if _convoy_phase not in ("idle", "stopped", "error"):
            return False, f"이미 convoy 실행 중입니다 (phase={_convoy_phase})"

        _convoy_phase = "entering"
        _convoy_stop_event = threading.Event()
        _convoy_graceful_event = threading.Event()
        _convoy_robots = robots_config[:]
        _convoy_robot_status = {rc["robot_id"]: {"status": "waiting"} for rc in robots_config}
        _convoy_at_stop = {rc["robot_id"]: None for rc in robots_config}

    # 오케스트레이터 스레드 시작
    t = threading.Thread(
        target=_convoy_orchestrator,
        args=(robots_config, work_poi_names, stop_names),
        daemon=True,
        name="convoy-orchestrator",
    )
    t.start()
    robot_ids = [rc['robot_id'] for rc in robots_config]
    robot_names = [rc.get('robot_name') or f"로봇 {rc['robot_id']}" for rc in robots_config]
    logger.info(f"[Convoy] 오케스트레이터 시작 — 로봇: {robot_ids}")
    log_activity("convoy", "convoy_start",
                 f"Convoy 대열 작업 시작 (로봇: {', '.join(robot_names)})",
                 source="start_convoy")
    return True, "Convoy 대열 작업이 시작되었습니다"


# ─── Convoy 정지 ───────────────────────────────────────────────────────────────

def stop_convoy() -> tuple[bool, str]:
    """그레이스풀 정지 — 모든 로봇 WORK1 복귀 후 충전소 귀환"""
    global _convoy_phase

    with _convoy_lock:
        if _convoy_phase in ("idle", "stopped"):
            return False, "실행 중인 convoy가 없습니다"
        if _convoy_graceful_event:
            _convoy_graceful_event.set()
        _convoy_phase = "returning"

    logger.info("[Convoy] 그레이스풀 정지 요청")
    log_activity("convoy", "convoy_stop_request",
                 "Convoy 그레이스풀 정지 요청",
                 source="stop_convoy")
    return True, "Convoy 정지 요청 — 모든 로봇이 WORK1 복귀 후 충전소로 돌아갑니다"


def force_stop_convoy() -> tuple[bool, str]:
    """즉시 정지 — 모든 로봇 이동 취소 + 상태 리셋"""
    global _convoy_phase

    with _convoy_lock:
        robots = _convoy_robots[:]
        # stop_event 세팅 → 모든 워커 스레드 즉시 탈출
        if _convoy_stop_event:
            _convoy_stop_event.set()
        if _convoy_graceful_event:
            _convoy_graceful_event.set()
        _convoy_phase = "stopped"
        _convoy_robot_status.clear()
        _convoy_at_stop.clear()

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

    logger.info("[Convoy] 즉시 정지 완료 — 모든 이동 취소됨")
    log_activity("convoy", "convoy_force_stop",
                 "Convoy 즉시 정지 — 모든 로봇 이동 취소",
                 source="force_stop_convoy")
    return True, "Convoy 즉시 정지 — 모든 로봇 이동 취소됨"


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

            wait_event = None  # 5초 간격 출발이므로 wait_event 불필요
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

        # 순차적으로 시작: 5초 간격으로 출발
        INTER_ROBOT_DELAY = 7

        for i, (t, rc) in enumerate(zip(worker_threads, robots_config)):
            if stop_event.is_set():
                break

            logger.info(f"[Convoy] 로봇 {rc['robot_id']} 워커 시작 (#{i+1})")
            _rname = rc.get('robot_name') or f"로봇 {rc['robot_id']}"
            log_activity("convoy", "convoy_robot_depart",
                         f"Convoy 로봇 '{_rname}' 출발 (#{i+1})",
                         robot_id=rc['robot_id'], robot_name=_rname, source="_convoy_orchestrator")
            t.start()

            if i < len(robots_config) - 1:
                logger.info(f"[Convoy] {INTER_ROBOT_DELAY}초 후 다음 로봇 출발")
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

        # 모든 워커 종료 대기
        for t in worker_threads:
            t.join()

        logger.info("[Convoy] 모든 로봇 워커 종료")
        log_activity("convoy", "convoy_complete",
                     "Convoy 모든 로봇 작업 종료",
                     source="_convoy_orchestrator")

        with _convoy_lock:
            _convoy_phase = "stopped"

    except Exception as e:
        logger.exception(f"[Convoy] 오케스트레이터 예외: {e}")
        with _convoy_lock:
            _convoy_phase = "error"


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
            logger.info(f"[Robot {robot_id}] 활성 맵 ID: {target_map_id}")

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

            # ── 배터리 최소값 조회 ──
            robot_row = db.query(Robot).filter(Robot.id == robot_id).first()
            min_battery = robot_row.min_battery if robot_row else 20

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
            logger.warning(f"[Robot {robot_id}] WS 연결 실패 — HTTP 폴백: {e}")

        # ── 1단계: 앞 로봇 WORK1 도착 대기 ──
        if wait_event:
            _update_robot_status(robot_id, "waiting", message="앞 로봇 출발 대기")
            logger.info(f"[Robot {robot_id}] 앞 로봇 WORK1 도착 대기 중...")
            while not wait_event.is_set():
                if stop_event.is_set():
                    _update_robot_status(robot_id, "stopped")
                    return
                wait_event.wait(timeout=1.0)
            logger.info(f"[Robot {robot_id}] 앞 로봇 도착 확인 → 출발")

        # ── 2단계: 진입 경로 이동 (충전소 → WORK1) ──
        if entry_pois:
            # 잔여 이동 취소
            cancel_and_verify(robot_ip)

            first_work = work_pois[0]  # WORK1
            all_entry = entry_pois + [first_work]

            coords_parts = []
            for ep in all_entry:
                ex = ep.world_x if ep.world_x is not None else ep.x
                ey = ep.world_y if ep.world_y is not None else ep.y
                coords_parts.extend([str(ex), str(ey)])

            tx = first_work.world_x if first_work.world_x is not None else first_work.x
            ty = first_work.world_y if first_work.world_y is not None else first_work.y
            t_angle = first_work.angle if first_work.angle is not None else 0.0
            route_coords = ",".join(coords_parts) if len(coords_parts) > 2 else ""

            _update_robot_status(robot_id, "entering",
                                 current_poi=first_work.name,
                                 message="진입 경로 이동 중")

            logger.info(f"[Robot {robot_id}] 진입 경로: "
                        f"{'→'.join(p.name for p in all_entry)}")

            ws, result, detail = _execute_move(
                robot_id, robot_ip, tx, ty, t_angle, route_coords,
                ws, move_lock, stop_event)

            if result == "cancelled" or stop_event.is_set():
                _update_robot_status(robot_id, "stopped")
                return
            if result != "succeeded":
                _update_robot_status(robot_id, "error",
                                     message=f"진입 경로 실패: {result} {detail}")
                return

            logger.info(f"[Robot {robot_id}] WORK1 도착 완료")
        else:
            # 진입 경로 없으면 바로 시작
            cancel_and_verify(robot_ip)

        # ── 3단계: arrival_event 세팅 (뒤 로봇 출발 허용) ──
        arrival_event.set()
        with _convoy_lock:
            _convoy_at_stop[robot_id] = None  # WORK1 도착, 이동 준비

        # ── 4단계: 세그먼트 작업 루프 ──
        # 세그먼트 빌드: 정지점(WORK2, WORK4) 기준으로 구간 분할
        n_pois = len(work_pois)
        segments = []  # [(start_idx, end_idx, [경유 인덱스들])]
        seg_start = 0
        while True:
            path = []
            idx = seg_start
            while True:
                idx = (idx + 1) % n_pois
                path.append(idx)
                if work_pois[idx].name in stop_set or idx == 0:
                    break
            segments.append((seg_start, idx, path))
            seg_start = idx
            if idx == 0:
                break

        _update_robot_status(robot_id, "running", current_poi=work_pois[0].name)
        logger.info(f"[Robot {robot_id}] 세그먼트 루프 시작 "
                    f"({len(segments)}구간, 정지점: {list(stop_set)})")

        loop_count = 0
        current_node = 0
        graceful_finishing = False
        low_battery_break = False

        while not stop_event.is_set():
            # 그레이스풀: WORK1에 있으면 복귀 시작
            if graceful_event.is_set() and current_node == 0:
                break

            if current_node == 0:
                loop_count += 1
                logger.info(f"[Robot {robot_id}] ── 루프 {loop_count} 시작 ──")

                # ── 배터리 체크 (2회차부터) ──
                if loop_count >= 2:
                    battery_pct = _get_battery_percentage(robot_ip)
                    if battery_pct is not None:
                        logger.info(f"[Robot {robot_id}] 배터리: {battery_pct:.1f}% (최소: {min_battery}%)")
                        if battery_pct <= min_battery:
                            logger.warning(f"[Robot {robot_id}] 배터리 부족! "
                                           f"{battery_pct:.1f}% <= {min_battery}% — 단독 복귀")
                            # DB 위치 재배치 (배터리 낮은 순: C3→C2→C1→W1)
                            _reassign_convoy_positions()
                            _update_robot_status(robot_id, "low_battery",
                                                 message=f"배터리 부족 ({battery_pct:.0f}%) — 충전소 복귀")
                            low_battery_break = True
                            break

            if graceful_event.is_set() and not graceful_finishing:
                graceful_finishing = True
                logger.info(f"[Robot {robot_id}] 그레이스풀 — 현재 루프 완주 후 WORK1 복귀")

            # ── 현재 위치에 맞는 세그먼트 찾기 ──
            seg = None
            for s in segments:
                if s[0] == current_node:
                    seg = s
                    break
            if seg is None:
                logger.error(f"[Robot {robot_id}] 세그먼트 못 찾음 (node={current_node})")
                break

            _, seg_end_idx, seg_path = seg
            target_poi = work_pois[seg_end_idx]
            current_poi = work_pois[current_node]
            next_stop_name = _find_next_stop(work_pois, current_node, stop_set)
            is_stop_point = target_poi.name in stop_set

            # ── 정지점이 목적지면: 다른 로봇이 그 정지점에 있는지 확인 ──
            if is_stop_point:
                waited = False
                while not stop_event.is_set():
                    with _convoy_lock:
                        occupied = any(
                            pos == seg_end_idx
                            for rid, pos in _convoy_at_stop.items()
                            if rid != robot_id and pos is not None
                        )
                    if not occupied:
                        break
                    if not waited:
                        logger.info(f"[Robot {robot_id}] '{target_poi.name}' 점유 — 대기")
                        with _task_lock:
                            _run_info[robot_id] = {
                                "status": "running", "loop": loop_count,
                                "current_poi": current_poi.name,
                                "next_stop": next_stop_name,
                                "message": f"{target_poi.name} 대기 중",
                            }
                        waited = True
                    time.sleep(0.3)

                if stop_event.is_set():
                    break

            # ── 목적지 좌표 (along_given_route — 진입 경로처럼 전체 경유지 포함) ──
            tx = target_poi.world_x if target_poi.world_x is not None else target_poi.x
            ty = target_poi.world_y if target_poi.world_y is not None else target_poi.y
            t_angle = target_poi.angle if target_poi.angle is not None else 0.0

            # 시작점 + 경유 POI + 끝점 모두 포함 (진입 경로와 동일 방식)
            coords_parts = []
            cx = current_poi.world_x if current_poi.world_x is not None else current_poi.x
            cy = current_poi.world_y if current_poi.world_y is not None else current_poi.y
            coords_parts.extend([str(cx), str(cy)])
            for path_idx in seg_path:
                p = work_pois[path_idx]
                px = p.world_x if p.world_x is not None else p.x
                py = p.world_y if p.world_y is not None else p.y
                coords_parts.extend([str(px), str(py)])
            route_coords = ",".join(coords_parts)

            move_desc = f"{current_poi.name} → {target_poi.name}"
            status_msg = "finishing" if graceful_finishing else "running"
            _update_robot_status(robot_id, status_msg,
                                 current_poi=target_poi.name, loop=loop_count)
            with _task_lock:
                _run_info[robot_id] = {
                    "status": "running", "loop": loop_count,
                    "current_poi": target_poi.name,
                    "next_stop": next_stop_name,
                    "message": move_desc,
                }

            logger.info(f"[Robot {robot_id}] {move_desc} ({len(seg_path)}칸)"
                        f"{' (완주 중)' if graceful_finishing else ''}")

            # ── 이동 전 WS 재연결 (대기 중 끊김 방지) ──
            try:
                if ws:
                    ws.close()
            except Exception:
                pass
            ws = None
            try:
                ws = _create_planning_ws(robot_ip)
            except Exception as e:
                logger.warning(f"[Robot {robot_id}] 이동 전 WS 재연결 실패 — HTTP 폴백: {e}")

            # ── 이동 실행 (정지점은 도착 정밀도 0.1m, 장애물 감지 시 1.5초 대기) ──
            stop_accuracy = 0.1 if (is_stop_point or seg_end_idx == 0) else None
            ws, result, detail = _execute_move(
                robot_id, robot_ip, tx, ty, t_angle, route_coords,
                ws, move_lock, stop_event, target_accuracy=stop_accuracy,
                cancel_on_stuck=True, stuck_delay=1.5)

            if result == "cancelled" or stop_event.is_set():
                break
            if result == "stuck_limit":
                _update_robot_status(robot_id, "error",
                                     message="장애물 반복 감지 — 정지")
                logger.error(f"[Robot {robot_id}] 장애물 10회 — 작업 중단")
                return
            if result != "succeeded":
                logger.warning(f"[Robot {robot_id}] 이동 실패 ({result}) — 재시도")
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
                if result != "succeeded":
                    _update_robot_status(robot_id, "error",
                                         message=f"이동 실패: {result} {detail}")
                    return

            # ── 도착 ──
            current_node = seg_end_idx
            logger.info(f"[Robot {robot_id}] '{target_poi.name}' 도착")

            # 그레이스풀 완주 체크
            if graceful_finishing and current_node == 0:
                logger.info(f"[Robot {robot_id}] WORK1 도착 — 루프 완주 완료")
                break

            if graceful_event.is_set() and not graceful_finishing:
                graceful_finishing = True
                logger.info(f"[Robot {robot_id}] 그레이스풀 신호 수신 — 현재 루프 완주 후 WORK1 복귀")

            # ── 정지점이면 2초 대기 후 자동 진행 ──
            if is_stop_point:
                with _convoy_lock:
                    _convoy_at_stop[robot_id] = seg_end_idx

                logger.info(f"[Robot {robot_id}] 정지점 '{target_poi.name}' — 2초 대기")

                with _task_lock:
                    _run_info[robot_id] = {
                        "status": "waiting_confirmation",
                        "loop": loop_count,
                        "current_poi": target_poi.name,
                        "next_stop": next_stop_name,
                    }
                _update_robot_status(robot_id, "waiting_confirmation",
                                     current_poi=target_poi.name, loop=loop_count)

                # 정확히 2초 대기
                for _ in range(20):
                    if stop_event.is_set():
                        break
                    time.sleep(0.1)

                with _task_lock:
                    _run_info[robot_id] = {
                        "status": "running", "loop": loop_count,
                        "current_poi": target_poi.name,
                        "next_stop": next_stop_name,
                        "message": f"{target_poi.name} 확인 완료",
                    }

                # 정지점 해제
                with _convoy_lock:
                    _convoy_at_stop[robot_id] = None

                if stop_event.is_set():
                    break

                logger.info(f"[Robot {robot_id}] '{target_poi.name}' 2초 대기 완료 → 다음 구간")
                _update_robot_status(robot_id, "running",
                                     current_poi=target_poi.name, loop=loop_count)

        # ── 5단계: 그레이스풀 정지 / 배터리 부족 → WORK1 복귀 → 충전소 귀환 ──
        if graceful_event.is_set() or stop_event.is_set() or low_battery_break:
            logger.info(f"[Robot {robot_id}] 정지 신호 수신 — 복귀 시작")

            # 정지점 정리 (루프에서 나감)
            with _convoy_lock:
                _convoy_at_stop[robot_id] = None

            # WORK1으로 복귀 (현재 위치가 WORK1이 아닌 경우)
            if current_node != 0:
                home_poi = work_pois[0]
                hx = home_poi.world_x if home_poi.world_x is not None else home_poi.x
                hy = home_poi.world_y if home_poi.world_y is not None else home_poi.y
                h_angle = home_poi.angle if home_poi.angle is not None else 0.0

                # 현재 위치 → WORK1 (트랙 따라 이동)
                cur_poi = work_pois[current_node]
                cx = cur_poi.world_x if cur_poi.world_x is not None else cur_poi.x
                cy = cur_poi.world_y if cur_poi.world_y is not None else cur_poi.y
                route_coords = f"{cx},{cy},{hx},{hy}"

                _update_robot_status(robot_id, "returning",
                                     current_poi=home_poi.name,
                                     message="WORK1 복귀 중")

                with _task_lock:
                    _run_info[robot_id] = {
                        "status": "moving_to_start",
                        "current_poi": home_poi.name,
                        "message": "WORK1 복귀 중",
                    }

                logger.info(f"[Robot {robot_id}] WORK1 복귀 이동")
                ws, result, detail = _execute_move(
                    robot_id, robot_ip, hx, hy, h_angle, route_coords,
                    ws, move_lock, stop_event)

                if result != "succeeded":
                    logger.warning(f"[Robot {robot_id}] WORK1 복귀 실패: {result}")

            # ── DB에서 최신 위치 재조회 (배터리 재배치 반영) ──
            _cur_start_type = start_poi_type
            _cur_charging_poi = charging_poi
            _cur_standby_poi = standby_poi
            _cur_return_pois = return_pois

            db2 = SessionLocal()
            try:
                robot_row2 = db2.query(Robot).filter(Robot.id == robot_id).first()
                if robot_row2:
                    if robot_row2.charging_id:
                        cpoi = db2.query(MapPOI).filter(
                            MapPOI.id == robot_row2.charging_id, MapPOI.is_active == True
                        ).first()
                        if cpoi:
                            db2.expunge(cpoi)
                            _cur_charging_poi = cpoi
                            _cur_standby_poi = None
                            _cur_start_type = "charging"
                            # 복귀 경로: ENTER-LAST → {충전소이름}-1
                            new_return_names = ["ENTER-LAST", f"{cpoi.name}-1"]
                            _cur_return_pois = []
                            for rn in new_return_names:
                                rp = db2.query(MapPOI).filter(
                                    MapPOI.name == rn, MapPOI.is_active == True,
                                    MapPOI.map_id == work_pois[0].map_id,
                                ).first()
                                if rp:
                                    db2.expunge(rp)
                                    _cur_return_pois.append(rp)
                            _ensure_world_coords(db2, _cur_return_pois + [_cur_charging_poi], robot_id)
                            logger.info(f"[Robot {robot_id}] 재배치 위치: {cpoi.name} (충전소)")
                    elif robot_row2.standby_id:
                        spoi = db2.query(MapPOI).filter(
                            MapPOI.id == robot_row2.standby_id, MapPOI.is_active == True
                        ).first()
                        if spoi:
                            db2.expunge(spoi)
                            _cur_standby_poi = spoi
                            _cur_charging_poi = None
                            _cur_start_type = "standby"
                            new_return_names = ["ENTER-LAST", f"{spoi.name}-1"]
                            _cur_return_pois = []
                            for rn in new_return_names:
                                rp = db2.query(MapPOI).filter(
                                    MapPOI.name == rn, MapPOI.is_active == True,
                                    MapPOI.map_id == work_pois[0].map_id,
                                ).first()
                                if rp:
                                    db2.expunge(rp)
                                    _cur_return_pois.append(rp)
                            _ensure_world_coords(db2, _cur_return_pois + [_cur_standby_poi], robot_id)
                            logger.info(f"[Robot {robot_id}] 재배치 위치: {spoi.name} (대기지점)")
            except Exception as e:
                logger.warning(f"[Robot {robot_id}] 위치 재조회 실패 — 기존 위치 사용: {e}")
            finally:
                db2.close()

            # ── 복귀 경로 이동 (WORK1 → 경유 POI → 최종 목적지) ──
            if _cur_return_pois:
                return_dest = "충전소" if _cur_start_type == "charging" else "대기지점"
                _update_robot_status(robot_id, "charging_route",
                                     message=f"{return_dest} 복귀 중")
                with _task_lock:
                    _run_info[robot_id] = {
                        "status": "charging_route",
                        "message": f"{return_dest} 복귀 중",
                    }

                target_poi = _cur_return_pois[-1]
                coords_parts = []

                w1 = work_pois[0]
                w1x = w1.world_x if w1.world_x is not None else w1.x
                w1y = w1.world_y if w1.world_y is not None else w1.y
                coords_parts.extend([str(w1x), str(w1y)])

                for rp in _cur_return_pois:
                    rx = rp.world_x if rp.world_x is not None else rp.x
                    ry = rp.world_y if rp.world_y is not None else rp.y
                    coords_parts.extend([str(rx), str(ry)])

                tx = target_poi.world_x if target_poi.world_x is not None else target_poi.x
                ty = target_poi.world_y if target_poi.world_y is not None else target_poi.y

                if len(_cur_return_pois) > 1:
                    prev_rp = _cur_return_pois[-2]
                    prev_x = prev_rp.world_x if prev_rp.world_x is not None else prev_rp.x
                    prev_y = prev_rp.world_y if prev_rp.world_y is not None else prev_rp.y
                else:
                    prev_x = w1x
                    prev_y = w1y
                dx = float(tx) - float(prev_x)
                dy = float(ty) - float(prev_y)
                t_angle = math.atan2(dy, dx) if (dx != 0 or dy != 0) else 0.0

                route_coords = ",".join(coords_parts) if len(coords_parts) > 2 else ""

                logger.info(f"[Robot {robot_id}] {return_dest} 복귀: "
                            f"WORK1→{'→'.join(p.name for p in _cur_return_pois)}"
                            f" (도착 각도: {math.degrees(t_angle):.1f}°)")

                ws, result, detail = _execute_move(
                    robot_id, robot_ip, tx, ty, t_angle, route_coords,
                    ws, move_lock, stop_event)

                if result != "succeeded":
                    logger.warning(f"[Robot {robot_id}] 복귀 경로 실패: {result}")

            # ── 최종 목적지: 충전소 도킹 또는 대기지점 이동 ──
            if _cur_start_type == "standby" and _cur_standby_poi:
                sx = _cur_standby_poi.world_x if _cur_standby_poi.world_x is not None else _cur_standby_poi.x
                sy = _cur_standby_poi.world_y if _cur_standby_poi.world_y is not None else _cur_standby_poi.y
                s_angle = _cur_standby_poi.angle if _cur_standby_poi.angle is not None else 0.0

                logger.info(f"[Robot {robot_id}] 대기지점 '{_cur_standby_poi.name}' 최종 이동")

                ws, result, detail = _execute_move(
                    robot_id, robot_ip, sx, sy, s_angle, "",
                    ws, move_lock, stop_event)

                if result != "succeeded":
                    logger.warning(f"[Robot {robot_id}] 대기지점 이동 실패: {result}")

                _update_robot_status(robot_id, "standby", message="대기지점 복귀 완료")
                with _task_lock:
                    _run_info[robot_id] = {
                        "status": "standby",
                        "message": "대기지점 복귀 완료",
                    }
            else:
                time.sleep(1)
                cname = _cur_charging_poi.name if _cur_charging_poi else None
                ok, msg = send_charge(robot_ip, charger_name=cname)
                logger.info(f"[Robot {robot_id}] 충전 도킹 명령 (charger={cname}): ok={ok}, {msg}")

                _update_robot_status(robot_id, "charging", message="충전 중")
                with _task_lock:
                    _run_info[robot_id] = {
                        "status": "charging",
                        "message": "충전 중",
                    }

            # return_ready_event 세팅 (앞 로봇 복귀 허용)
            return_ready_event.set()
            return

        # 정상 종료 (stop_event에 의한)
        _update_robot_status(robot_id, "stopped")
        return_ready_event.set()

    except Exception as e:
        logger.exception(f"[Robot {robot_id}] 워커 예외: {e}")
        _update_robot_status(robot_id, "error", message=str(e))
        arrival_event.set()  # 뒤 로봇 블록 방지
        return_ready_event.set()
    finally:
        if ws:
            try:
                ws.close()
            except Exception:
                pass
        # 정지점 정리 (비정상 종료 시 안전장치)
        with _convoy_lock:
            _convoy_at_stop.pop(robot_id, None)
        # 태블릿 상태 정리
        with _task_lock:
            _confirm_events.pop(robot_id, None)
            _stuck_states.pop(robot_id, None)
        logger.info(f"[Robot {robot_id}] 워커 스레드 종료")


# ─── 헬퍼 함수들 ──────────────────────────────────────────────────────────────

def _update_robot_status(robot_id: int, status: str, **kwargs):
    """convoy 로봇 상태 업데이트"""
    with _convoy_lock:
        _convoy_robot_status[robot_id] = {"status": status, **kwargs}


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
    stuck_delay: float = 3.0,
) -> tuple:
    """이동 실행 + 완료 대기 (재시도 포함)
    cancel_on_stuck: 장애물 감지 시 취소 후 stuck_delay초 대기 → 재시도
    반환: (ws, result, detail)
    """
    result = ""
    detail = ""
    stuck_retries = 0
    MAX_STUCK_RETRIES = 10  # 장애물 재시도 상한

    for attempt in range(1, max_retries + 1):
        if stop_event.is_set():
            return ws, "cancelled", ""

        with move_lock:
            if attempt > 1:
                logger.info(f"[Robot {robot_id}] 이동 재시도 {attempt}/{max_retries}")
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

            logger.info(f"[Robot {robot_id}] Move {move_id} 전송")

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

        logger.info(f"[Robot {robot_id}] 이동 결과: {result} {detail}")

        # 장애물 감지 → 3초 대기 후 같은 이동 재시도 (attempt 소모 안 함)
        if result == "stuck":
            if stuck_retries >= MAX_STUCK_RETRIES:
                logger.error(f"[Robot {robot_id}] 장애물 {MAX_STUCK_RETRIES}회 감지 — 정지")
                cancel_and_verify(robot_ip)
                return ws, "stuck_limit", f"장애물 {MAX_STUCK_RETRIES}회 초과"
            stuck_retries += 1
            logger.info(f"[Robot {robot_id}] 장애물 대기 {stuck_delay}초 "
                        f"({stuck_retries}/{MAX_STUCK_RETRIES})")
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
