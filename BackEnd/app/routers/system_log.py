from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.crud.system_log import get_system_logs, get_distinct_categories, get_distinct_actions

router = APIRouter(prefix="/api/system-logs", tags=["시스템 로그"])


@router.get("")
def api_get_system_logs(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    category: str | None = Query(None),
    action: str | None = Query(None),
    message: str | None = Query(None),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    db: Session = Depends(get_db),
):
    """시스템 로그 목록 조회 (필터: category, action, message, 날짜 범위)"""
    items, total = get_system_logs(
        db, skip=skip, limit=limit,
        category=category, action=action, message=message,
        date_from=date_from, date_to=date_to,
    )
    return {"total": total, "items": items}


@router.get("/categories")
def api_get_categories(db: Session = Depends(get_db)):
    """저장된 카테고리 목록"""
    return get_distinct_categories(db)


@router.get("/actions")
def api_get_actions(db: Session = Depends(get_db)):
    """저장된 액션 목록"""
    return get_distinct_actions(db)
