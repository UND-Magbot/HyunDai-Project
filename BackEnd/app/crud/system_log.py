from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.models.system_log import SystemLog
from app.schemas.system_log import SystemLogResponse

KST = timezone(timedelta(hours=9))


def _today_range() -> tuple[datetime, datetime]:
    now_kst = datetime.now(KST)
    start = now_kst.replace(hour=0, minute=0, second=0, microsecond=0).replace(tzinfo=None)
    end = start + timedelta(days=1)
    return start, end


def _to_response(log: SystemLog) -> SystemLogResponse:
    return SystemLogResponse(
        id=log.id,
        category=log.category,
        action=log.action,
        message=log.message,
        detail=log.detail,
        robot_id=log.robot_id,
        robot_name=log.robot_name,
        source=log.source,
        created_at=log.created_at,
    )


def get_system_logs(
    db: Session,
    skip: int = 0,
    limit: int = 100,
    category: str | None = None,
    action: str | None = None,
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

    if category:
        query = query.filter(SystemLog.category == category)
    if action:
        query = query.filter(SystemLog.action == action)
    if message:
        query = query.filter(SystemLog.message.ilike(f"%{message}%"))

    total = query.count()
    items = query.order_by(desc(SystemLog.created_at)).offset(skip).limit(limit).all()
    return [_to_response(log) for log in items], total


def get_distinct_categories(db: Session) -> list[str]:
    rows = db.query(SystemLog.category).distinct().all()
    return sorted([r[0] for r in rows if r[0]])


def get_distinct_actions(db: Session) -> list[str]:
    rows = db.query(SystemLog.action).distinct().all()
    return sorted([r[0] for r in rows if r[0]])
