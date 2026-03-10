from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.models.activity_log import ActivityLog
from app.models.system_log import SystemLog

KST = timezone(timedelta(hours=9))

# activity_log.category → 화면 표시 카테고리
_ACTIVITY_CATEGORY_MAP = {
    "robot":  "로봇",
    "system": "시스템",
}
# convoy / task / map / user / 그 외 → 사용자


def _activity_display_category(category: str) -> str:
    return _ACTIVITY_CATEGORY_MAP.get(category, "사용자")


def _today_range() -> tuple[datetime, datetime]:
    now_kst = datetime.now(KST)
    start = now_kst.replace(hour=0, minute=0, second=0, microsecond=0).replace(tzinfo=None)
    end = start + timedelta(days=1)
    return start, end


def get_unified_logs(
    db: Session,
    skip: int = 0,
    limit: int = 50,
    display_category: str | None = None,  # '사용자' | '시스템' | '로봇' | None (전체)
    message: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> tuple[list[dict], int]:
    """activity_logs + system_logs 통합 조회 (created_at 내림차순)

    display_category:
      None   → 전체 (두 테이블 모두)
      '사용자' → activity_logs (category in convoy/task/map/user/...)
      '시스템' → activity_logs (category=system) + system_logs 전체
      '로봇'  → activity_logs (category=robot)
    """
    if date_from is None and date_to is None:
        date_from, date_to = _today_range()

    rows: list[dict] = []

    # ── activity_logs 조회 ──────────────────────────────────────────────────
    include_activity = display_category in (None, "사용자", "시스템", "로봇")
    if include_activity:
        aq = db.query(ActivityLog)
        if date_from:
            aq = aq.filter(ActivityLog.created_at >= date_from)
        if date_to:
            aq = aq.filter(ActivityLog.created_at < date_to)
        if message:
            aq = aq.filter(ActivityLog.message.ilike(f"%{message}%"))

        if display_category == "사용자":
            aq = aq.filter(ActivityLog.category.notin_(["robot", "system"]))
        elif display_category == "시스템":
            aq = aq.filter(ActivityLog.category == "system")
        elif display_category == "로봇":
            aq = aq.filter(ActivityLog.category == "robot")
        # None → 필터 없음

        for log in aq.all():
            rows.append({
                "id": f"a{log.id}",
                "display_category": _activity_display_category(log.category),
                "action": log.action,
                "message": log.message,
                "detail": log.detail,
                "robot_id": log.robot_id,
                "robot_name": log.robot_name,
                "source": log.source,
                "created_at": log.created_at,
            })

    # ── system_logs 조회 ────────────────────────────────────────────────────
    include_system = display_category in (None, "시스템")
    if include_system:
        sq = db.query(SystemLog)
        if date_from:
            sq = sq.filter(SystemLog.created_at >= date_from)
        if date_to:
            sq = sq.filter(SystemLog.created_at < date_to)
        if message:
            sq = sq.filter(SystemLog.message.ilike(f"%{message}%"))

        for log in sq.all():
            rows.append({
                "id": f"s{log.id}",
                "display_category": "시스템",
                "action": log.action,
                "message": log.message,
                "detail": log.detail,
                "robot_id": log.robot_id,
                "robot_name": log.robot_name,
                "source": log.source,
                "created_at": log.created_at,
            })

    # ── 정렬 → 페이지네이션 ─────────────────────────────────────────────────
    rows.sort(key=lambda x: x["created_at"] or datetime.min, reverse=True)
    total = len(rows)
    return rows[skip: skip + limit], total
