from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.menu import MenuListResponse
from app.schemas.auth import AuthUser
from app.crud.auth import get_current_user
from app.crud.menu import get_all_menus

router = APIRouter(prefix="/api/menus", tags=["메뉴"])


@router.get("", response_model=MenuListResponse)
def api_get_menus(
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(get_current_user),
):
    """좌측 탭 메뉴 트리 구조 조회

    프론트엔드 연동:
      GET /api/menus
      Header: Authorization: Bearer <token>
      → { "items": [{ "id": 1, "menu_key": "monitoring", ... , "children": [...] }] }
    """
    items = get_all_menus(db)
    return MenuListResponse(items=items)
