from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class SystemLogResponse(BaseModel):
    id: int
    category: str
    action: str
    message: str
    detail: Optional[str] = None
    robot_id: Optional[int] = None
    robot_name: Optional[str] = None
    source: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True
