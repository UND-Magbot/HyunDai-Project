from pydantic import BaseModel
from datetime import datetime


class PermissionGrant(BaseModel):
    """권한 부여 요청 — 체크된 menu_id 목록"""
    menu_ids: list[int]


class PermissionItem(BaseModel):
    """권한 단건 응답"""
    id: int
    menu_id: int
    menu_key: str
    menu_name: str
    granted_by: int | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class PermissionResponse(BaseModel):
    """사용자별 권한 목록 응답"""
    user_id: int
    menu_ids: list[int]
    items: list[PermissionItem]
