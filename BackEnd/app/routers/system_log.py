from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.crud.system_log import get_system_logs, get_distinct_levels, get_distinct_loggers

router = APIRouter(prefix="/api/system-logs", tags=["시스템 로그"])


@router.get("")
def api_get_system_logs(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    level: str | None = Query(None),
    logger_name: str | None = Query(None),
    message: str | None = Query(None),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    db: Session = Depends(get_db),
):
    """시스템 로그 목록 조회 (필터: level, logger_name, message, 날짜 범위)"""
    items, total = get_system_logs(
        db, skip=skip, limit=limit,
        level=level, logger_name=logger_name, message=message,
        date_from=date_from, date_to=date_to,
    )
    return {"total": total, "items": items}


@router.get("/levels")
def api_get_levels(db: Session = Depends(get_db)):
    """저장된 로그 레벨 목록 (드롭다운용)"""
    return get_distinct_levels(db)


@router.get("/loggers")
def api_get_loggers(db: Session = Depends(get_db)):
    """저장된 로거 이름 목록 (드롭다운용)"""
    return get_distinct_loggers(db)
