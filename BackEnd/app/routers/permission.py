from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.auth import AuthUser
from app.schemas.permission import PermissionGrant, PermissionResponse
from app.crud.auth import get_current_user, require_admin
from app.crud.permission import get_user_permissions, update_user_permissions
from app.crud.activity_log import log_activity

router = APIRouter(prefix="/api/permissions", tags=["권한 관리"])


@router.get("/me", response_model=PermissionResponse)
def api_get_my_permissions(
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(get_current_user),
):
    """현재 로그인한 사용자의 메뉴 권한 조회

    프론트엔드 연동:
      GET /api/permissions/me
      Header: Authorization: Bearer <token>
      → { "user_id": 2, "menu_ids": [1, 3, 5], "items": [...] }
    """
    return get_user_permissions(db, current_user.id)


@router.get("/{user_id}", response_model=PermissionResponse)
def api_get_permissions(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(require_admin),
):
    """특정 사용자의 메뉴 권한 조회 (관리자 전용)

    프론트엔드 연동:
      GET /api/permissions/{user_id}
      Header: Authorization: Bearer <token>
      → { "user_id": 2, "menu_ids": [1, 3, 5], "items": [...] }
    """
    return get_user_permissions(db, user_id)


@router.put("/{user_id}", response_model=PermissionResponse)
def api_update_permissions(
    user_id: int,
    data: PermissionGrant,
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(require_admin),
):
    """사용자의 메뉴 권한 일괄 갱신 (관리자 전용)

    프론트엔드 연동:
      PUT /api/permissions/{user_id}
      Header: Authorization: Bearer <token>
      Body: { "menu_ids": [1, 3, 5] }
      → { "user_id": 2, "menu_ids": [1, 3, 5], "items": [...] }
    """
    result = update_user_permissions(db, user_id, data.menu_ids, current_user.id)
    log_activity(
        "system", "permission_update",
        f"사용자 ID {user_id}의 메뉴 권한 변경: {data.menu_ids}",
        source="api_update_permissions",
    )
    return result
