from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.menu import Menu, UserPermission
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
    # 변경 전 권한 조회
    before_rows = (
        db.query(UserPermission, Menu.menu_name)
        .join(Menu, UserPermission.menu_id == Menu.id)
        .filter(UserPermission.user_id == user_id)
        .all()
    )
    before_ids = {row.UserPermission.menu_id for row in before_rows}
    before_names = {row.UserPermission.menu_id: row.menu_name for row in before_rows}

    result = update_user_permissions(db, user_id, data.menu_ids, current_user.id)

    # 변경 후 메뉴 이름 조회
    after_ids = set(data.menu_ids)
    added_ids = after_ids - before_ids
    removed_ids = before_ids - after_ids

    after_menus = {m.id: m.menu_name for m in db.query(Menu).filter(Menu.id.in_(added_ids)).all()} if added_ids else {}

    added_names = [after_menus.get(i, str(i)) for i in sorted(added_ids)]
    removed_names = [before_names.get(i, str(i)) for i in sorted(removed_ids)]

    parts = []
    if added_names:
        parts.append(f"추가: {', '.join(added_names)}")
    if removed_names:
        parts.append(f"제거: {', '.join(removed_names)}")
    diff_str = " / ".join(parts) if parts else "변경 없음"

    # 대상 사용자 이름 조회
    from app.models.user import User as UserModel
    target_user = db.query(UserModel).filter(UserModel.id == user_id).first()
    target_name = target_user.login_id if target_user else f"ID {user_id}"

    log_activity(
        "system", "permission_update",
        f"[{current_user.login_id}] '{target_name}' 권한 변경 — {diff_str}",
        source="api_update_permissions",
    )
    return result
