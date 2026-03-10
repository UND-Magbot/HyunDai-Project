import logging  # reload trigger

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

# 로깅 설정 — 백그라운드 스레드 로그도 터미널에 출력
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.database import init_db
from app.routers import user, robot, auth, map, task, alarm_log, convoy, activity_log, system_log, backup, log, acs, menu, permission
from app.services.wcs_service import start_wcs_reporter, stop_wcs_reporter

# 모델 import (테이블 메타데이터 등록용)
import app.models  # noqa: F401


@asynccontextmanager
async def lifespan(application: FastAPI):
    # 서버 시작 시 DB + 테이블 자동 생성
    init_db()

    # 시스템 로그 → DB 자동 저장
    # uvicorn이 dictConfig로 로깅을 재설정하므로,
    # lifespan 시점에 각 로거에 직접 핸들러를 등록해야 함
    from app.log_handler import DBLogHandler
    db_handler = DBLogHandler()
    target_loggers = [
        logging.getLogger(),              # 루트 (앱 코드)
        logging.getLogger("uvicorn"),      # uvicorn 코어 (uvicorn.error가 여기로 전파됨)
        logging.getLogger("uvicorn.access"),  # 접속 로그 (propagate=False라 별도 등록)
    ]
    for lgr in target_loggers:
        lgr.addHandler(db_handler)

    start_wcs_reporter()

    yield

    stop_wcs_reporter()

    for lgr in target_loggers:
        lgr.removeHandler(db_handler)


app = FastAPI(
    title="RCS API",
    description="Robot Control System — 사용자 / 로봇 관리 API",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS (프론트 연결용)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 라우터 등록
app.include_router(auth.router)
app.include_router(user.router)
app.include_router(robot.router)
app.include_router(map.router)
app.include_router(task.router)
app.include_router(alarm_log.router)
app.include_router(convoy.router)
app.include_router(activity_log.router)
app.include_router(system_log.router)
app.include_router(backup.router)
app.include_router(log.router)
app.include_router(acs.router)
app.include_router(menu.router)
app.include_router(permission.router)


# 정적 파일 서빙 (맵 이미지 등)
_static_dir = Path(__file__).resolve().parent.parent / "static"
_static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")


@app.get("/ping")
def ping():
    return {"message": "pong"}
