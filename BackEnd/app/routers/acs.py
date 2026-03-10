"""ACS 수신 엔드포인트
- WCS → ACS: 화재 경보 수신 (POST /acs/fireinfo)
"""
import logging
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from app.robot_api.robot_convoy_service import fire_evacuate

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/acs", tags=["ACS 인터페이스"])


class FireInfoRequest(BaseModel):
    # Body 필드는 WCS 측과 협의 예정 — 현재는 자유 형식 수신
    model_config = {"extra": "allow"}


@router.post("/fireinfo")
def receive_fire_info(body: FireInfoRequest):
    """WCS → ACS: 화재 경보 수신"""
    data = body.model_dump()
    logger.warning(f"[ACS] 화재 경보 수신: {data}")

    ok, msg = fire_evacuate()
    logger.warning(f"[ACS] 대피 시작: {msg} (ok={ok})")

    return {
        "httpStatus": "OK",
        "httpStatusCode": 200,
        "httpStatusMessage": "지시 수신 완료",
        "bodyData": [],
    }
