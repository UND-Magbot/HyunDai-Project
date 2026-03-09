import logging
import subprocess
import time
from datetime import datetime

from fastapi import APIRouter
from fastapi.responses import Response

from app.database import DB_USER, DB_PASSWORD, DB_HOST, DB_PORT, DB_NAME

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/backup", tags=["DB 백업"])


@router.get("/db")
def api_backup_db():
    """DB 전체 백업 — mysqldump로 SQL 파일 생성 후 다운로드"""
    now = datetime.now()
    date_str = now.strftime("%y%m%d")
    millis = str(int(now.timestamp() * 1000))[:6]
    filename = f"db_backup_{date_str}_{millis}.sql"

    cmd = [
        "mysqldump",
        f"--host={DB_HOST}",
        f"--port={DB_PORT}",
        f"--user={DB_USER}",
        f"--password={DB_PASSWORD}",
        "--default-character-set=utf8mb4",
        DB_NAME,
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            timeout=120,
        )
    except FileNotFoundError:
        logger.error("[backup] mysqldump 명령어를 찾을 수 없습니다")
        return Response(
            content='{"detail": "mysqldump 명령어를 찾을 수 없습니다. 서버에 MariaDB 클라이언트가 설치되어 있는지 확인해주세요."}',
            status_code=500,
            media_type="application/json",
        )
    except subprocess.TimeoutExpired:
        logger.error("[backup] mysqldump 타임아웃 (120초)")
        return Response(
            content='{"detail": "백업 시간이 초과되었습니다 (120초)."}',
            status_code=500,
            media_type="application/json",
        )

    if result.returncode != 0:
        err_msg = result.stderr.decode("utf-8", errors="replace").strip()
        logger.error(f"[backup] mysqldump 실패: {err_msg}")
        return Response(
            content=f'{{"detail": "백업 실패: {err_msg}"}}',
            status_code=500,
            media_type="application/json",
        )

    logger.info(f"[backup] DB 백업 완료: {filename} ({len(result.stdout)} bytes)")

    return Response(
        content=result.stdout,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
