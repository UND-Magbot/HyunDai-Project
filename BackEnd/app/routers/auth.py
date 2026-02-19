from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.auth import LoginRequest, LoginResponse, AuthUser
from app.schemas.user import ROLE_MAP
from app.crud.auth import authenticate_user, create_access_token, get_current_user

router = APIRouter(prefix="/api/auth", tags=["인증"])


@router.post("/login", response_model=LoginResponse)
def login(data: LoginRequest, db: Session = Depends(get_db)):
    """로그인 — JWT 토큰 발급

    프론트엔드 연동:
      POST /api/auth/login
      Body: { "login_id": "admin", "password": "Admin1234!" }
      → { "access_token": "...", "token_type": "bearer", "user": {...} }
    """
    user, role_code = authenticate_user(db, data.login_id, data.password)
    token = create_access_token(user.id, role_code)

    return LoginResponse(
        access_token=token,
        user=AuthUser(
            id=user.id,
            login_id=user.login_id,
            username=user.username,
            role=role_code,
            role_name=ROLE_MAP.get(role_code, "Unknown"),
        ),
    )


@router.get("/me", response_model=AuthUser)
def get_me(current_user: AuthUser = Depends(get_current_user)):
    """현재 로그인한 사용자 정보 조회

    프론트엔드 연동:
      GET /api/auth/me
      Header: Authorization: Bearer <token>
      → { "id": 1, "login_id": "admin", "username": "관리자", "role": 1, "role_name": "Administrator" }
    """
    return current_user
