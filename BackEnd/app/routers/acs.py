"""ACS 수신 엔드포인트
- WCS → ACS: 화재 경보 수신 (POST /acs/fireinfo)
"""
import logging
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from app.robot_api.robot_convoy_service import fire_evacuate, reset_fire

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/acs", tags=["ACS 인터페이스"])


class FireInfoRequest(BaseModel):
    # Body 필드는 WCS 측과 협의 예정 — 현재는 자유 형식 수신
    model_config = {"extra": "allow"}


@router.post("/fireinfo")
def receive_fire_info(body: FireInfoRequest):
    """WCS → ACS: 화재 경보 수신"""
    data = body.model_dump()
    alarm_code = str(data.get("alarmCode", ""))
    logger.warning(f"[ACS] 화재 경보 수신: {data} (alarmCode={alarm_code})")

    if alarm_code == "1":
        ok, msg = fire_evacuate()
        logger.warning(f"[ACS] 화재 발생 → 대피 시작: {msg} (ok={ok})")
        message = "화재 경보 수신 — 대피 시작"
    elif alarm_code == "0":
        reset_fire()
        logger.info("[ACS] 화재 해제 → 경보 초기화 완료")
        message = "화재 해제 수신 — 경보 초기화"
    else:
        logger.warning(f"[ACS] 알 수 없는 alarmCode: {alarm_code}")
        message = f"알 수 없는 alarmCode: {alarm_code}"

    return {
        "httpStatus": "OK",
        "httpStatusCode": 200,
        "httpStatusMessage": message,
        "bodyData": [],
    }
