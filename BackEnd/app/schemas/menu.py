from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class MenuBase(BaseModel):
    menu_key: str
    menu_name: str
    parent_id: Optional[int] = None
    sort_order: int = 0
    is_active: bool = True


class MenuTreeItem(BaseModel):
    """트리 구조 응답용 (재귀)"""
    id: int
    menu_key: str
    menu_name: str
    parent_id: Optional[int] = None
    sort_order: int
    is_active: bool
    children: list["MenuTreeItem"] = []

    model_config = {"from_attributes": True}


class MenuListResponse(BaseModel):
    """메뉴 트리 목록 응답"""
    items: list[MenuTreeItem]
