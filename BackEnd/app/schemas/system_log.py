from datetime import datetime
from typing import Optional

from pydantic import BaseModel


LEVEL_MAP = {
    "DEBUG": "디버그",
    "INFO": "정보",
    "WARNING": "경고",
    "ERROR": "에러",
    "CRITICAL": "치명적",
}


class SystemLogResponse(BaseModel):
    id: int
    level: str
    level_name: str
    logger_name: str
    message: str
    module: Optional[str] = None
    func_name: Optional[str] = None
    line_no: Optional[int] = None
    exc_text: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True
