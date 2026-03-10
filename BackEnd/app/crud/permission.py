from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from app.models.menu import Menu, UserPermission
from app.models.user import User
from app.schemas.permission import PermissionItem, PermissionResponse


def get_user_permissions(db: Session, user_id: int) -> PermissionResponse:
    """특정 사용자의 메뉴 권한 목록 조회"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="사용자를 찾지 못했습니다.")

    perms = (
        db.query(UserPermission)
        .join(Menu)
        .filter(UserPermission.user_id == user_id)
        .all()
    )
    items = [
        PermissionItem(
            id=p.id,
            menu_id=p.menu_id,
            menu_key=p.menu.menu_key,
            menu_name=p.menu.menu_name,
            granted_by=p.granted_by,
            created_at=p.created_at,
        )
        for p in perms
    ]
    return PermissionResponse(
        user_id=user_id,
        menu_ids=[p.menu_id for p in perms],
        items=items,
    )


def update_user_permissions(
    db: Session, user_id: int, menu_ids: list[int], granted_by: int
) -> PermissionResponse:
    """사용자의 메뉴 권한을 일괄 갱신 (기존 권한 삭제 후 새로 부여)"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="사용자를 찾지 못했습니다.")

    # 자기 자신에게 권한 부여 방지 (admin은 이미 전체 접근)
    if user_id == granted_by:
        raise HTTPException(
            status_code=400, detail="자기 자신에게는 권한을 부여할 수 없습니다."
        )

    # 유효한 menu_id인지 확인
    if menu_ids:
        valid_menus = db.query(Menu.id).filter(Menu.id.in_(menu_ids)).all()
        valid_ids = {m.id for m in valid_menus}
        invalid_ids = set(menu_ids) - valid_ids
        if invalid_ids:
            raise HTTPException(
                status_code=400,
                detail=f"존재하지 않는 메뉴 ID: {invalid_ids}",
            )

    # 기존 권한 전체 삭제
    db.query(UserPermission).filter(UserPermission.user_id == user_id).delete()

    # 새 권한 부여
    for mid in menu_ids:
        db.add(UserPermission(user_id=user_id, menu_id=mid, granted_by=granted_by))

    db.commit()

    return get_user_permissions(db, user_id)
