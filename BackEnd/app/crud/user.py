from sqlalchemy.orm import Session
from fastapi import HTTPException, status
from passlib.hash import bcrypt

from app.models.user import User, UserRole
from app.models.menu import Menu, UserPermission
from app.schemas.user import UserCreate, UserUpdate, UserResponse, ROLE_MAP

# 일반 사용자 기본 메뉴 권한
DEFAULT_USER_MENU_KEYS = ("monitoring", "settings")


def _to_response(user: User) -> UserResponse:
    """User ORM 객체 → UserResponse 변환"""
    role_code = user.role.role if user.role else 2
    return UserResponse(
        id=user.id,
        login_id=user.login_id,
        username=user.username,
        role=role_code,
        role_name=ROLE_MAP.get(role_code, "Unknown"),
        is_active=user.is_active,
        created_at=user.created_at,
        updated_at=user.updated_at,
    )


# ── DB-01 사용자 등록 ──
def create_user(db: Session, data: UserCreate) -> UserResponse:
    # 중복 ID 체크
    exists = db.query(User).filter(User.login_id == data.login_id).first()
    if exists:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"이미 존재하는 로그인 ID입니다: {data.login_id}",
        )

    user = User(
        login_id=data.login_id,
        password_hash=bcrypt.hash(data.password),
        username=data.username,
    )
    db.add(user)
    db.flush()  # user.id 확보

    user_role = UserRole(user_id=user.id, role=data.role)
    db.add(user_role)

    # 관리자(role=1)는 전체 메뉴, 일반 사용자(role=2)는 기본 메뉴 권한 부여
    if data.role == 1:
        all_menus = db.query(Menu).all()
        for menu in all_menus:
            db.add(UserPermission(user_id=user.id, menu_id=menu.id))
    else:
        default_menus = (
            db.query(Menu)
            .filter(Menu.menu_key.in_(DEFAULT_USER_MENU_KEYS))
            .all()
        )
        for menu in default_menus:
            db.add(UserPermission(user_id=user.id, menu_id=menu.id))

    db.commit()
    db.refresh(user)

    return _to_response(user)


# ── 사용자 단건 조회 ──
def get_user(db: Session, user_id: int) -> UserResponse:
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="사용자를 찾지 못했습니다.")
    return _to_response(user)


# ── login_id로 조회 ──
def get_user_by_login_id(db: Session, login_id: str) -> UserResponse:
    user = db.query(User).filter(User.login_id == login_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="사용자를 찾지 못했습니다.")
    return _to_response(user)


# ── 사용자 목록 조회 ──
def get_users(db: Session, skip: int = 0, limit: int = 100) -> list[UserResponse]:
    users = db.query(User).offset(skip).limit(limit).all()
    return [_to_response(u) for u in users]


# ── DB-02 사용자 수정 ──
def update_user(db: Session, user_id: int, data: UserUpdate) -> UserResponse:
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="사용자를 찾지 못했습니다.")

    if data.password is not None:
        user.password_hash = bcrypt.hash(data.password)

    if data.is_active is not None:
        user.is_active = data.is_active

    if data.role is not None and user.role:
        user.role.role = data.role

    db.commit()
    db.refresh(user)
    return _to_response(user)


# ── DB-03 사용자 삭제 (Soft Delete) ──
def delete_user(db: Session, user_id: int) -> dict:
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="사용자를 찾지 못했습니다.")

    # TODO: 진행 중인 작업이 있는지 확인 (JOB 모듈 연동 시 구현)
    # active_jobs = db.query(Job).filter(Job.assigned_user_id == user_id, Job.status == 1).count()
    # if active_jobs > 0:
    #     raise HTTPException(status_code=409, detail="진행 중인 작업이 있어 삭제할 수 없습니다.")

    user.is_active = False  # Soft Delete
    db.commit()

    return {"message": f"사용자 '{user.username}'이(가) 비활성화되었습니다.", "user_id": user_id}
