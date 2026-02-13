from pydantic import BaseModel, Field
from datetime import datetime


class LoginRequest(BaseModel):
    """로그인 요청 — 프론트엔드의 login_id/password 필드에 대응"""
    login_id: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class LoginResponse(BaseModel):
    """로그인 응답 — access_token을 프론트엔드 localStorage에 저장"""
    access_token: str
    token_type: str = "bearer"
    user: "AuthUser"


class AuthUser(BaseModel):
    """인증된 사용자 정보"""
    id: int
    login_id: str
    username: str
    role: int
    role_name: str

    model_config = {"from_attributes": True}
