"""WCS 인터페이스 서비스
- ACS → WCS: 로봇 상태 주기적 보고 (POST /adapter-inf/report/status)
- 각 로봇에 WebSocket 연결 → /tracked_pose, /battery_state 실시간 수신 → DB 업데이트
- WCS 설정: 환경변수 WCS_URL, WCS_REPORT_INTERVAL
"""
import json
import logging
import os
import threading
import time

import httpx
from websocket import create_connection, WebSocketException

from app.database import SessionLocal
from app.models.robot import Robot, RobotStatus, RobotStatusHistory
from app.crud.activity_log import log_activity

logger = logging.getLogger(__name__)

# 환경변수 설정
WCS_URL = os.getenv("WCS_URL", "")                          # 예: http://192.168.0.100:8080
WCS_REPORT_INTERVAL = int(os.getenv("WCS_REPORT_INTERVAL", "30"))  # 초 단위

ROBOT_PORT = 8090

_STATUS_CODE_MAP = {
    0: (0, "대기"),
    1: (0, "작업중"),
    2: (0, "충전중"),
    3: (3, "에러"),
    4: (4, "오프라인"),
}

# ── 로봇별 최신 데이터 캐시 (WS에서 실시간 갱신) ──
# {ip: {"x": float, "y": float, "ori": float, "battery": int, "charging": str, "online": bool}}
_robot_cache: dict[str, dict] = {}
_cache_lock = threading.Lock()
_ws_threads: list[threading.Thread] = []


def _robot_ws_loop(ip: str, stop_event: threading.Event):
    """로봇 1대에 WS 연결 → /tracked_pose + /battery_state 수신 → 캐시 갱신"""
    ws_url = f"ws://{ip}:{ROBOT_PORT}/ws/v2/topics"
    subscribe_msg = json.dumps({
        "enable_topic": "/tracked_pose"
    })
    subscribe_battery = json.dumps({
        "enable_topic": "/battery_state"
    })

    while not stop_event.is_set():
        try:
            ws = create_connection(ws_url, timeout=5)
            ws.send(subscribe_msg)
            ws.send(subscribe_battery)
            ws.settimeout(5)

            with _cache_lock:
                if ip not in _robot_cache:
                    _robot_cache[ip] = {"x": 0.0, "y": 0.0, "ori": 0.0,
                                        "battery": 0, "charging": "unknown", "online": True}
                else:
                    _robot_cache[ip]["online"] = True

            while not stop_event.is_set():
                try:
                    raw = ws.recv()
                    msg = json.loads(raw)
                    topic = msg.get("topic")

                    with _cache_lock:
                        cache = _robot_cache.setdefault(
                            ip, {"x": 0.0, "y": 0.0, "ori": 0.0,
                                 "battery": 0, "charging": "unknown", "online": True})

                    if topic == "/tracked_pose" and msg.get("pos"):
                        with _cache_lock:
                            cache["x"] = msg["pos"][0]
                            cache["y"] = msg["pos"][1]
                            cache["ori"] = msg.get("ori", 0.0)
                            cache["online"] = True
                    elif topic == "/battery_state":
                        with _cache_lock:
                            cache["battery"] = int(msg.get("percentage", 0))
                            cache["charging"] = msg.get("charging_status", "unknown")
                            cache["online"] = True
                except (WebSocketException, TimeoutError, OSError):
                    break
                except json.JSONDecodeError:
                    continue

            try:
                ws.close()
            except Exception:
                pass

        except Exception:
            # 연결 실패 → 오프라인 마킹
            with _cache_lock:
                cache = _robot_cache.setdefault(
                    ip, {"x": 0.0, "y": 0.0, "ori": 0.0,
                         "battery": 0, "charging": "unknown", "online": False})
                cache["online"] = False

        # 재연결 대기 (5초)
        if not stop_event.is_set():
            stop_event.wait(5)


def _sync_cache_to_db(db, robots: list[tuple[Robot, "RobotStatus | None"]]):
    """캐시 데이터를 DB RobotStatus에 반영. status 변경 시 RobotStatusHistory에도 기록 (가용성 통계용)."""
    transitions: list[RobotStatusHistory] = []
    for i, (robot, status) in enumerate(robots):
        if not status:
            status = RobotStatus(robot_id=robot.id, status=4)
            db.add(status)
            db.flush()
            robots[i] = (robot, status)

        prev_status = status.status

        with _cache_lock:
            cache = _robot_cache.get(robot.ip_address)

        if cache and cache.get("online"):
            status.position_x = cache["x"]
            status.position_y = cache["y"]
            status.position_yaw = cache["ori"]
            status.battery_level = cache["battery"]
            # charging_status 매핑
            cs = cache.get("charging", "unknown")
            if cs in ("charging", "Charging"):
                status.charging_status = 1
                status.status = 2  # 충전중
            elif cs in ("fully_charged", "Full"):
                status.charging_status = 2
                # 완충도 도킹된 충전 상태 — status=2 유지로 충전중 ↔ 대기중 깜빡임 방지
                if status.status in (0, 4):
                    status.status = 2
            else:
                status.charging_status = 0
                if status.status == 4:
                    status.status = 0  # 오프라인→대기
        else:
            status.status = 4  # 오프라인

        # status 전이 시점만 이력 저장 (MTTR/MTBF 계산용 — 같은 상태 반복 INSERT 안 함)
        if status.status != prev_status:
            transitions.append(RobotStatusHistory(
                robot_id=robot.id,
                battery_level=status.battery_level,
                charging_status=status.charging_status,
                position_x=status.position_x,
                position_y=status.position_y,
                position_yaw=status.position_yaw,
                status=status.status,
            ))

    if transitions:
        db.add_all(transitions)

    try:
        db.commit()
    except Exception as e:
        logger.warning(f"[WCS] 상태 업데이트 DB 커밋 실패: {e}")
        db.rollback()


def _build_device_info(robot: Robot, status: RobotStatus | None, seq: int) -> dict:
    st = status.status if status else 4
    comm_code = 0 if st == 4 else 1
    status_code, status_desc = _STATUS_CODE_MAP.get(st, (st, "알수없음"))

    loc_x = status.position_x if status else 0.0
    loc_y = status.position_y if status else 0.0
    loc_z = status.position_yaw if status else 0.0

    no = robot.wcs_no if robot.wcs_no else seq
    device_code = f"AMR{no:02d}"

    return {
        "eqCode": "ACS",
        "deviceCode": device_code,
        "commCode": comm_code,
        "statusCode": status_code,
        "statusDesc": status_desc,
        "pidCode": "",
        "cmdCode": "",
        "locCode": f"{loc_x},{loc_y},{loc_z}",
    }


def report_status_once() -> bool:
    """DB에서 로봇 목록 조회 → 캐시→DB 동기화 → WCS로 상태 전송."""
    if not WCS_URL:
        return False

    db = SessionLocal()
    try:
        robots = (
            db.query(Robot, RobotStatus)
            .outerjoin(RobotStatus, Robot.id == RobotStatus.robot_id)
            .filter(Robot.is_active == True)
            .order_by(Robot.id)
            .all()
        )
        # 캐시 → DB 동기화
        _sync_cache_to_db(db, robots)

        device_info = [_build_device_info(r, s, i + 1) for i, (r, s) in enumerate(robots)]
    finally:
        db.close()

    payload = {"deviceInfo": device_info}
    target = f"{WCS_URL.rstrip('/')}/adapter-inf/report/status"

    try:
        resp = httpx.post(target, json=payload, timeout=5)
        if resp.status_code == 200:
            logger.info(f"[WCS] 상태 보고 성공 ({len(device_info)}대)")
            summary = ", ".join(
                f"{d['deviceCode']}({d['statusDesc']})" for d in device_info
            )
            detail = json.dumps(payload, ensure_ascii=False)
            log_activity("system", "wcs_report",
                         f"WCS 상태 보고 성공 ({len(device_info)}대): {summary}",
                         detail=detail,
                         source="wcs_service")
            return True
        else:
            logger.warning(f"[WCS] 상태 보고 실패: HTTP {resp.status_code}")
            log_activity("system", "wcs_report_fail",
                         f"WCS 상태 보고 실패: HTTP {resp.status_code}",
                         source="wcs_service")
            return False
    except Exception as e:
        logger.warning(f"[WCS] 상태 보고 연결 오류: {e}")
        log_activity("system", "wcs_report_fail",
                     f"WCS 상태 보고 연결 오류: {e}",
                     source="wcs_service")
        return False


def _reporter_loop(stop_event: threading.Event):
    logger.info(f"[WCS] 상태 보고 시작 (대상: {WCS_URL}, 주기: {WCS_REPORT_INTERVAL}s)")
    while not stop_event.wait(WCS_REPORT_INTERVAL):
        report_status_once()


def _start_robot_ws_connections(stop_event: threading.Event):
    """DB에서 활성 로봇 목록 조회 → 각 로봇에 WS 연결 스레드 시작."""
    db = SessionLocal()
    try:
        robots = db.query(Robot).filter(Robot.is_active == True).all()
        ips = [r.ip_address for r in robots]
    finally:
        db.close()

    for ip in ips:
        t = threading.Thread(target=_robot_ws_loop, args=(ip, stop_event), daemon=True)
        t.start()
        _ws_threads.append(t)
        logger.info(f"[WCS] 로봇 WS 연결 시작: {ip}")


_stop_event: threading.Event | None = None
_thread: threading.Thread | None = None


def start_wcs_reporter():
    """FastAPI lifespan에서 호출 — WCS URL이 설정된 경우에만 시작."""
    global _stop_event, _thread
    if not WCS_URL:
        logger.info("[WCS] WCS_URL 미설정 — 상태 보고 비활성화")
        return
    _stop_event = threading.Event()

    # 로봇 WS 연결 시작 (위치/배터리 실시간 수신)
    _start_robot_ws_connections(_stop_event)

    # WCS 보고 루프 시작
    _thread = threading.Thread(target=_reporter_loop, args=(_stop_event,), daemon=True)
    _thread.start()


def stop_wcs_reporter():
    """FastAPI lifespan 종료 시 호출."""
    if _stop_event:
        _stop_event.set()
