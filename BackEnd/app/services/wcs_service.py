"""WCS 인터페이스 서비스
- ACS → WCS: 로봇 상태 주기적 보고 (POST /adapter-inf/report/status)
- WCS 설정: 환경변수 WCS_URL, WCS_REPORT_INTERVAL
"""
import logging
import os
import threading
import time

import httpx

from app.database import SessionLocal
from app.models.robot import Robot, RobotStatus

logger = logging.getLogger(__name__)

# 환경변수 설정
WCS_URL = os.getenv("WCS_URL", "")                          # 예: http://192.168.0.100:8080
WCS_REPORT_INTERVAL = int(os.getenv("WCS_REPORT_INTERVAL", "10"))  # 초 단위

_STATUS_CODE_MAP = {
    0: (0, "대기"),
    1: (0, "작업중"),
    2: (0, "충전중"),
    3: (3, "에러"),
    4: (4, "오프라인"),
}


def _build_device_info(robot: Robot, status: RobotStatus | None, seq: int) -> dict:
    st = status.status if status else 4
    comm_code = 0 if st == 4 else 1
    status_code, status_desc = _STATUS_CODE_MAP.get(st, (st, "알수없음"))

    loc_x = status.position_x if status else 0.0
    loc_y = status.position_y if status else 0.0
    loc_z = status.position_yaw if status else 0.0

    no = robot.wcs_no if robot.wcs_no else seq  # wcs_no 우선, 미설정 시 순서 fallback
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
    """DB에서 로봇 목록 조회 후 WCS로 상태 전송. 성공 시 True 반환."""
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
        device_info = [_build_device_info(r, s, i + 1) for i, (r, s) in enumerate(robots)]
    finally:
        db.close()

    payload = {"deviceInfo": device_info}
    target = f"{WCS_URL.rstrip('/')}/adapter-inf/report/status"

    try:
        resp = httpx.post(target, json=payload, timeout=5)
        if resp.status_code == 200:
            logger.debug(f"[WCS] 상태 보고 성공 ({len(device_info)}대)")
            return True
        else:
            logger.warning(f"[WCS] 상태 보고 실패: HTTP {resp.status_code}")
            return False
    except Exception as e:
        logger.warning(f"[WCS] 상태 보고 연결 오류: {e}")
        return False


def _reporter_loop(stop_event: threading.Event):
    logger.info(f"[WCS] 상태 보고 시작 (대상: {WCS_URL}, 주기: {WCS_REPORT_INTERVAL}s)")
    while not stop_event.wait(WCS_REPORT_INTERVAL):
        report_status_once()


_stop_event: threading.Event | None = None
_thread: threading.Thread | None = None


def start_wcs_reporter():
    """FastAPI lifespan에서 호출 — WCS URL이 설정된 경우에만 시작."""
    global _stop_event, _thread
    if not WCS_URL:
        logger.info("[WCS] WCS_URL 미설정 — 상태 보고 비활성화")
        return
    _stop_event = threading.Event()
    _thread = threading.Thread(target=_reporter_loop, args=(_stop_event,), daemon=True)
    _thread.start()


def stop_wcs_reporter():
    """FastAPI lifespan 종료 시 호출."""
    if _stop_event:
        _stop_event.set()
