import logging  # reload trigger
import threading

# Thread stack size: 8MB → 1MB
# 컨테이너 mem_limit 안에서 동시 thread 수를 8배 늘림
# Python 핸들러는 1MB 스택으로 충분 (재귀 깊은 코드 없음)
# 효과: mem_limit 4GB / 1MB = ~3600개 thread 가능 (이전 220개)
threading.stack_size(1024 * 1024)

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
from app.routers import user, robot, auth, map, task, alarm_log, convoy, activity_log, system_log, backup, log, acs, menu, permission, statistics
from app.services.wcs_service import start_wcs_reporter, stop_wcs_reporter

# 모델 import (테이블 메타데이터 등록용)
import app.models  # noqa: F401


@asynccontextmanager
async def lifespan(application: FastAPI):
    # ── anyio worker thread pool 한도 명시 (thread 누수 방지) ──
    # FastAPI의 sync def 핸들러는 anyio worker pool에서 실행됨.
    # 기본값(default 40)이지만, 명시 설정해서 무한 확장 가능성 차단.
    # 5번 서버에서 발생한 "RuntimeError: can't start new thread" 재발 방지.
    try:
        from anyio import to_thread
        limiter = to_thread.current_default_thread_limiter()
        limiter.total_tokens = 100  # 동시 sync 핸들러 실행 한도 (운영 부하 대비 충분)
        logging.info(f"[startup] anyio thread limiter set: {limiter.total_tokens}")
    except Exception as e:
        logging.warning(f"[startup] anyio limiter 설정 실패 (무시): {e}")

    # asyncio default executor도 명시 한도 (백그라운드 sync 작업용)
    try:
        import asyncio
        from concurrent.futures import ThreadPoolExecutor
        loop = asyncio.get_running_loop()
        loop.set_default_executor(ThreadPoolExecutor(max_workers=50, thread_name_prefix="asyncio-exec"))
        logging.info("[startup] asyncio default executor max_workers=50")
    except Exception as e:
        logging.warning(f"[startup] asyncio executor 설정 실패 (무시): {e}")

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

    # 시스템 로그 → 디스크 파일 자동 저장 (컨테이너 삭제돼도 호스트에 보존)
    # docker-compose.yml의 ./BackEnd/logs:/var/log/backend 볼륨에 마운트됨.
    # docker logs는 컨테이너 삭제 시 사라지므로, 영구 보관용 파일 핸들러 추가.
    #
    # 디스크 절감 정책:
    # - uvicorn.access (HTTP 요청 로그)는 file에서 제외 — backend.log의 ~90% 차지
    #   (분당 수백건의 GET /api/... 로그. 디버깅 시 docker logs로 충분)
    # - 파일 크기: 50MB × 5 = 최대 250MB (이전 1.1GB → 1/4로 감소)
    file_handler = None
    try:
        from logging.handlers import RotatingFileHandler
        log_dir = Path("/var/log/backend")
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_dir / "backend.log",
            maxBytes=50 * 1024 * 1024,   # 50MB
            backupCount=5,                # backend.log + .1 ~ .5 = 최대 300MB
            encoding="utf-8",
        )
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(logging.Formatter(
            "%(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))
        # uvicorn.access는 제외 (HTTP 요청 로그 — 파일 용량의 90% 차지)
        for lgr in target_loggers:
            if lgr.name == "uvicorn.access":
                continue
            lgr.addHandler(file_handler)
        logging.info(f"[startup] 파일 로그 핸들러 등록: {log_dir / 'backend.log'} (50MB×5, uvicorn.access 제외)")
    except Exception as e:
        logging.warning(f"[startup] 파일 로그 핸들러 등록 실패 (Docker 로그만 사용): {e}")

    start_wcs_reporter()

    # 배터리 로테이션 스케줄러 시작 (대기 상태 시 충전소 ↔ W 로봇 자동 교체)
    # ※ 일시 비활성화 — 작업 종료 후 C↔W 자동 교체 로직만 끔
    # ※ 작업 중 1시간 체크(_convoy_hourly_battery_check)는 convoy 시작 시 자동 스케줄되므로 영향 없음
    from app.robot_api.robot_convoy_service import start_battery_rotation, stop_battery_rotation
    start_battery_rotation()

    yield

    # stop_battery_rotation()
    stop_wcs_reporter()

    for lgr in target_loggers:
        lgr.removeHandler(db_handler)
        if file_handler is not None:
            lgr.removeHandler(file_handler)
    if file_handler is not None:
        try:
            file_handler.close()
        except Exception:
            pass


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
app.include_router(statistics.router)


# 정적 파일 서빙 (맵 이미지 등)
_static_dir = Path(__file__).resolve().parent.parent / "static"
_static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")


@app.get("/ping")
def ping():
    return {"message": "pong"}


@app.get("/healthz")
async def healthz():
    """초경량 healthcheck — DB/외부호출 없이 즉시 응답.
    autoheal/docker healthcheck 전용. 부하 spike 중에도 timeout 없이 응답해야 함.
    """
    return {"ok": True}


@app.get("/debug/threads")
def debug_threads(with_stack: bool = False, top: int = 0):
    """[디버그용] Python 레벨 thread 종류/개수 조회

    OS 레벨에서는 모두 'uvicorn'으로 보이지만, Python 레벨에서는
    threading.enumerate()로 각 thread의 이름/타입 확인 가능.
    누수 추적용. 운영 중에도 호출 안전 (read-only).

    Query params:
      - with_stack=true : 각 thread의 현재 stack trace 포함 (누수 위치 추적)
      - top=N : stack trace를 가장 많이 발견되는 위치 N개로 그룹화
                (예: top=10 → "함수 X에서 멈춰있는 thread 30개" 식 집계)
    """
    import threading
    import collections
    import sys
    import traceback

    threads = list(threading.enumerate())
    by_name_prefix: dict[str, int] = collections.defaultdict(int)
    by_daemon: dict[str, int] = collections.defaultdict(int)
    samples = []

    for t in threads:
        name = t.name or "<unnamed>"
        # 이름 prefix만 사용 (예: "convoy-robot-13" → "convoy-robot")
        prefix = name.rsplit("-", 1)[0] if "-" in name and name.rsplit("-", 1)[1].isdigit() else name
        by_name_prefix[prefix] += 1
        by_daemon["daemon" if t.daemon else "non-daemon"] += 1
        if len(samples) < 30:
            samples.append({"name": name, "daemon": t.daemon, "alive": t.is_alive()})

    result = {
        "total": len(threads),
        "by_name_prefix": dict(sorted(by_name_prefix.items(), key=lambda x: -x[1])),
        "by_daemon": dict(by_daemon),
        "samples_first_30": samples,
    }

    # Stack trace 옵션 — 누수 발생 시 어디 코드에서 멈춰있는지 추적
    if with_stack or top > 0:
        frames = sys._current_frames()
        stacks: dict[str, list[str]] = {}
        # 가장 안쪽(현재 실행 중) 프레임 위치별 카운트
        location_counts: dict[str, int] = collections.defaultdict(int)
        location_examples: dict[str, str] = {}

        for t in threads:
            frame = frames.get(t.ident)
            if frame is None:
                continue
            # 마지막 5프레임만 (너무 길면 응답 폭증)
            stack_lines = traceback.format_stack(frame, limit=5)
            if with_stack:
                stacks[t.name] = stack_lines
            # 가장 안쪽 위치 추출 (file:line in func 형태)
            if stack_lines:
                # "  File "...", line N, in func\n    code" 형태에서 file:line 추출
                last_frame = stack_lines[-1].strip().split("\n")[0]
                location_counts[last_frame] += 1
                if last_frame not in location_examples:
                    location_examples[last_frame] = t.name

        if with_stack:
            result["stacks"] = stacks

        if top > 0:
            top_locations = sorted(location_counts.items(), key=lambda x: -x[1])[:top]
            result["top_stack_locations"] = [
                {
                    "count": cnt,
                    "location": loc,
                    "example_thread": location_examples.get(loc, ""),
                }
                for loc, cnt in top_locations
            ]

    return result


@app.get("/debug/health")
def debug_health():
    """[디버그용] backend 종합 health check

    한 번의 호출로 thread/메모리/fd/DB 풀 상태 모두 확인.
    누수 발생 시 어디 자원이 고갈되고 있는지 빠르게 진단.
    """
    import threading
    import os
    import resource

    result: dict = {}

    # 1) Thread
    threads = threading.enumerate()
    result["threads"] = {
        "total": len(threads),
        "non_daemon": sum(1 for t in threads if not t.daemon),
        "daemon": sum(1 for t in threads if t.daemon),
    }

    # 2) Memory (RSS, in MB)
    try:
        rusage = resource.getrusage(resource.RUSAGE_SELF)
        result["memory"] = {
            "rss_mb": round(rusage.ru_maxrss / 1024, 1),  # Linux: KB → MB
        }
    except Exception as e:
        result["memory"] = {"error": str(e)}

    # 3) File descriptors
    try:
        fd_dir = "/proc/self/fd"
        if os.path.isdir(fd_dir):
            fds = os.listdir(fd_dir)
            result["file_descriptors"] = {
                "open_count": len(fds),
            }
            # fd 종류별 카운트 (소켓, 파일 등)
            fd_types: dict[str, int] = {}
            for fd in fds:
                try:
                    target = os.readlink(f"{fd_dir}/{fd}")
                    if "socket:" in target:
                        fd_types["socket"] = fd_types.get("socket", 0) + 1
                    elif "pipe:" in target:
                        fd_types["pipe"] = fd_types.get("pipe", 0) + 1
                    elif target.startswith("/"):
                        fd_types["file"] = fd_types.get("file", 0) + 1
                    else:
                        fd_types["other"] = fd_types.get("other", 0) + 1
                except OSError:
                    pass
            result["file_descriptors"]["by_type"] = fd_types
    except Exception as e:
        result["file_descriptors"] = {"error": str(e)}

    # 4) DB pool 상태
    try:
        from app.database import engine
        pool = engine.pool
        result["db_pool"] = {
            "size": pool.size(),
            "checked_in": pool.checkedin(),
            "checked_out": pool.checkedout(),
            "overflow": pool.overflow(),
        }
    except Exception as e:
        result["db_pool"] = {"error": str(e)}

    # 5) 위험 지표 — 한도 대비 사용률
    warnings = []
    if result["threads"]["total"] > 500:
        warnings.append(f"⚠️ thread 많음: {result['threads']['total']}개 (정상 50~150)")
    if "rss_mb" in result.get("memory", {}) and result["memory"]["rss_mb"] > 3000:
        warnings.append(f"⚠️ 메모리 많음: {result['memory']['rss_mb']}MB (limit 4GB)")
    if "open_count" in result.get("file_descriptors", {}) and result["file_descriptors"]["open_count"] > 1000:
        warnings.append(f"⚠️ fd 많음: {result['file_descriptors']['open_count']}개")
    if "checked_out" in result.get("db_pool", {}) and result["db_pool"]["checked_out"] > 50:
        warnings.append(f"⚠️ DB 세션 많이 점유: {result['db_pool']['checked_out']}개")

    result["warnings"] = warnings if warnings else ["all green"]

    return result


@app.get("/debug/leak-check")
def debug_leak_check(top: int = 10):
    """[디버그용] 누수 의심 위치 자동 진단

    - thread가 많이 멈춰있는 코드 위치 top N 반환
    - 같은 함수에서 멈춰있는 thread가 많으면 그 함수가 누수원
    - 30초 안에 진짜 누수 위치 짚을 수 있음
    """
    import threading
    import sys
    import collections

    threads = threading.enumerate()
    frames = sys._current_frames()

    # 가장 안쪽 프레임의 (file, line, func) 별 카운트
    location_counts: dict[tuple, int] = collections.defaultdict(int)
    location_threads: dict[tuple, list[str]] = collections.defaultdict(list)

    for t in threads:
        frame = frames.get(t.ident)
        if frame is None:
            continue
        # 가장 안쪽 프레임 (현재 실행 중)
        try:
            file_path = frame.f_code.co_filename
            line_no = frame.f_lineno
            func_name = frame.f_code.co_name
            # backend 코드만 (시스템 라이브러리는 노이즈)
            if "/app/app/" in file_path or "site-packages" not in file_path:
                key = (file_path, line_no, func_name)
                location_counts[key] += 1
                if len(location_threads[key]) < 3:
                    location_threads[key].append(t.name)
        except Exception:
            pass

    # 카운트 많은 순으로 정렬
    sorted_locations = sorted(location_counts.items(), key=lambda x: -x[1])[:top]

    return {
        "total_threads": len(threads),
        "suspicious_locations": [
            {
                "count": cnt,
                "file": file_path.replace("/app/app/", ""),
                "line": line_no,
                "function": func_name,
                "example_threads": location_threads[(file_path, line_no, func_name)],
            }
            for (file_path, line_no, func_name), cnt in sorted_locations
        ],
    }


@app.get("/debug/convoy-workers")
def debug_convoy_workers():
    """[디버그용] 컨보이 각 워커의 현재 상태 + 마지막 위치 + confirm_event 상태

    멈춤 발생 시 어떤 워커가 어디서 hang됐는지 1초 안에 진단 가능.
    """
    from app.robot_api.robot_convoy_service import (
        _convoy_robot_status,
        _convoy_node_positions,
        _convoy_phase,
        _convoy_robots,
        _confirm_events,
        _convoy_return_requested,
        _convoy_battery_cache,
    )

    workers = []
    for rc in _convoy_robots:
        rid = rc["robot_id"]
        ev = _confirm_events.get(rid)
        workers.append({
            "robot_id": rid,
            "ip": rc.get("ip"),
            "status": _convoy_robot_status.get(rid, {}),
            "node_position": _convoy_node_positions.get(rid),
            "battery_cached": _convoy_battery_cache.get(rid),
            "confirm_event_exists": ev is not None,
            "confirm_event_set": ev.is_set() if ev else None,
            "return_requested": rid in _convoy_return_requested,
        })

    return {
        "phase": _convoy_phase,
        "robot_count": len(_convoy_robots),
        "workers": workers,
        "return_requested_ids": list(_convoy_return_requested),
    }


@app.get("/health")
def health_check():
    """이중화 헬스체크 — DB 연결 + convoy 상태 확인"""
    from app.database import engine
    from sqlalchemy import text as sa_text
    import time

    result = {"status": "ok", "timestamp": time.time(), "checks": {}}

    # DB 연결 체크
    try:
        with engine.connect() as conn:
            conn.execute(sa_text("SELECT 1"))
        result["checks"]["database"] = "ok"
    except Exception as e:
        result["checks"]["database"] = f"error: {e}"
        result["status"] = "degraded"

    # convoy 상태 체크
    try:
        from app.robot_api.robot_convoy_service import _convoy_phase
        result["checks"]["convoy"] = _convoy_phase
    except Exception:
        result["checks"]["convoy"] = "unknown"

    return result
