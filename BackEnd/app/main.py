
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import init_db
from app.routers import user, robot, auth

# 모델 import (테이블 메타데이터 등록용)
import app.models  # noqa: F401


@asynccontextmanager
async def lifespan(application: FastAPI):
    # 서버 시작 시 DB + 테이블 자동 생성
    init_db()
    yield


app = FastAPI(
    title="RCS API",
    description="Robot Control System — 사용자 / 로봇 관리 API",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS (프론트 연결용)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 라우터 등록
app.include_router(auth.router)
app.include_router(user.router)
app.include_router(robot.router)


@app.get("/ping")
def ping():
    return {"message": "pong"}
