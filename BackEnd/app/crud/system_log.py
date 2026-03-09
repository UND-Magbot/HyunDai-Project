from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.models.system_log import SystemLog
from app.schemas.system_log import SystemLogResponse, LEVEL_MAP

KST = timezone(timedelta(hours=9))


def _today_range() -> tuple[datetime, datetime]:
    """오늘 자정(KST) ~ 내일 자정(KST)을 naive datetime 튜플로 반환"""
    now_kst = datetime.now(KST)
    start = now_kst.replace(hour=0, minute=0, second=0, microsecond=0).replace(tzinfo=None)
    end = start + timedelta(days=1)
    return start, end


def _to_response(log: SystemLog) -> SystemLogResponse:
    return SystemLogResponse(
        id=log.id,
        level=log.level,
        level_name=LEVEL_MAP.get(log.level, log.level),
        logger_name=log.logger_name,
        message=log.message,
        module=log.module,
        func_name=log.func_name,
        line_no=log.line_no,
        exc_text=log.exc_text,
        created_at=log.created_at,
    )


def get_system_logs(
    db: Session,
    skip: int = 0,
    limit: int = 100,
    level: str | None = None,
    logger_name: str | None = None,
    message: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> tuple[list[SystemLogResponse], int]:
    query = db.query(SystemLog)

    if date_from or date_to:
        if date_from:
            query = query.filter(SystemLog.created_at >= date_from)
        if date_to:
            query = query.filter(SystemLog.created_at <= date_to)
    else:
        today_start, today_end = _today_range()
        query = query.filter(SystemLog.created_at >= today_start, SystemLog.created_at < today_end)

    if level:
        query = query.filter(SystemLog.level == level)
    if logger_name:
        query = query.filter(SystemLog.logger_name.ilike(f"%{logger_name}%"))
    if message:
        query = query.filter(SystemLog.message.ilike(f"%{message}%"))

    total = query.count()
    items = query.order_by(desc(SystemLog.created_at)).offset(skip).limit(limit).all()
    return [_to_response(log) for log in items], total


def get_distinct_levels(db: Session) -> list[dict]:
    rows = db.query(SystemLog.level).distinct().all()
    return [
        {"code": r[0], "name": LEVEL_MAP.get(r[0], r[0])}
        for r in sorted(rows, key=lambda x: x[0])
    ]


def get_distinct_loggers(db: Session) -> list[str]:
    rows = db.query(SystemLog.logger_name).distinct().all()
    return sorted([r[0] for r in rows])
