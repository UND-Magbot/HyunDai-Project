"""통계 라우터 — 가용성 지표 (MTTR / MTBF / 가용성 / 고장 횟수)
- robot_status_history 테이블의 status 전이를 기반으로 산출
- 정의:
    고장 = status=3 (에러) 진입 시점
    복구 = status=3 → 다른 값으로 전이 시점
    MTTR = Σ(복구시각 − 고장시각) / 고장 횟수
    MTBF = Σ(다음 고장시각 − 이전 고장시각) / (고장 횟수 - 1)
    가용성 = MTBF / (MTBF + MTTR) × 100
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import asc
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.robot import Robot, RobotStatusHistory

router = APIRouter(prefix="/api/statistics", tags=["통계"])

KST = timezone(timedelta(hours=9))


def _round_or_none(v: float | None, ndigits: int = 1) -> float | None:
    if v is None:
        return None
    return round(v, ndigits)


def _compute_for_robot(transitions: list[tuple[datetime, int]]) -> dict:
    """status 전이 시퀀스에서 가용성 지표 계산.
    transitions: [(recorded_at, status), ...]   recorded_at 오름차순.
    반환: { failure_count, mttr_seconds, mtbf_seconds, availability_pct, currently_in_failure }
    """
    failure_starts: list[datetime] = []
    repair_durations: list[float] = []   # 복구 소요 (초)
    last_error_start: datetime | None = None
    currently_in_failure = False

    for ts, st in transitions:
        if st == 3 and last_error_start is None:
            # 에러 진입
            last_error_start = ts
            failure_starts.append(ts)
            currently_in_failure = True
        elif st != 3 and last_error_start is not None:
            # 복구 — 이전 에러부터 지금까지가 MTTR 한 샘플
            delta = (ts - last_error_start).total_seconds()
            if delta >= 0:
                repair_durations.append(delta)
            last_error_start = None
            currently_in_failure = False

    failure_count = len(failure_starts)
    mttr = sum(repair_durations) / len(repair_durations) if repair_durations else None

    # MTBF — 고장과 다음 고장 사이의 평균 간격
    mtbf: float | None = None
    if len(failure_starts) >= 2:
        gaps = [
            (failure_starts[i + 1] - failure_starts[i]).total_seconds()
            for i in range(len(failure_starts) - 1)
        ]
        mtbf = sum(gaps) / len(gaps)

    # 가용성 — MTBF / (MTBF + MTTR)
    availability_pct: float | None = None
    if mttr is not None and mtbf is not None and (mtbf + mttr) > 0:
        availability_pct = mtbf / (mtbf + mttr) * 100
    elif failure_count == 0:
        # 한 번도 고장 안 났으면 100%
        availability_pct = 100.0
    elif mttr is None and mtbf is None and failure_count == 1:
        # 한 번 고장 나서 아직 복구 중이거나 복구 후 데이터 부족
        availability_pct = None

    return {
        "failure_count": failure_count,
        "mttr_seconds": _round_or_none(mttr, 1),
        "mtbf_seconds": _round_or_none(mtbf, 1),
        "availability_pct": _round_or_none(availability_pct, 2),
        "currently_in_failure": currently_in_failure,
    }


def _format_duration(seconds: float | None) -> str:
    """초 → 사람이 읽기 좋은 형태 ('1시간 23분 45초')"""
    if seconds is None:
        return "-"
    if seconds < 60:
        return f"{seconds:.0f}초"
    if seconds < 3600:
        m = int(seconds // 60)
        s = int(seconds % 60)
        return f"{m}분 {s}초" if s else f"{m}분"
    if seconds < 86400:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        return f"{h}시간 {m}분" if m else f"{h}시간"
    d = int(seconds // 86400)
    h = int((seconds % 86400) // 3600)
    return f"{d}일 {h}시간" if h else f"{d}일"


@router.get("/reliability")
def api_reliability(
    date_from: datetime | None = Query(None, description="시작 (KST 기준, 미지정 시 7일 전)"),
    date_to: datetime | None = Query(None, description="종료 (KST 기준, 미지정 시 지금)"),
    robot_id: int | None = Query(None, description="특정 로봇만 조회 (미지정 시 전체)"),
    db: Session = Depends(get_db),
):
    """가용성 지표 — MTTR / MTBF / 가용성 / 고장 횟수

    응답 구조:
    {
        "period": { "from": "...", "to": "..." },
        "summary": { ... },                   # 전체 평균
        "robots": [
            { robot_id, robot_name, failure_count, mttr_seconds, mtbf_seconds,
              availability_pct, mttr_text, mtbf_text, currently_in_failure }, ...
        ]
    }
    """
    # 기본 기간: 최근 7일
    if date_to is None:
        date_to = datetime.now(KST)
    if date_from is None:
        date_from = date_to - timedelta(days=7)

    # 로봇 목록
    q = db.query(Robot).filter(Robot.is_active == True)
    if robot_id:
        q = q.filter(Robot.id == robot_id)
    robots = q.order_by(Robot.id).all()

    # 로봇별 status 전이 일괄 조회
    robot_ids = [r.id for r in robots]
    history_q = (
        db.query(RobotStatusHistory.robot_id, RobotStatusHistory.recorded_at, RobotStatusHistory.status)
        .filter(RobotStatusHistory.robot_id.in_(robot_ids))
        .filter(RobotStatusHistory.recorded_at >= date_from)
        .filter(RobotStatusHistory.recorded_at <= date_to)
        .order_by(asc(RobotStatusHistory.robot_id), asc(RobotStatusHistory.recorded_at))
    )
    grouped: dict[int, list[tuple[datetime, int]]] = {rid: [] for rid in robot_ids}
    for rid, ts, st in history_q.all():
        grouped[rid].append((ts, st))

    robots_data = []
    sum_mttr, n_mttr = 0.0, 0
    sum_mtbf, n_mtbf = 0.0, 0
    sum_avail, n_avail = 0.0, 0
    total_failures = 0
    any_in_failure = False

    for r in robots:
        m = _compute_for_robot(grouped.get(r.id, []))
        robots_data.append({
            "robot_id": r.id,
            "robot_name": r.name,
            "wcs_label": f"AMR{r.wcs_no:02d}" if r.wcs_no else None,
            "failure_count": m["failure_count"],
            "mttr_seconds": m["mttr_seconds"],
            "mtbf_seconds": m["mtbf_seconds"],
            "availability_pct": m["availability_pct"],
            "mttr_text": _format_duration(m["mttr_seconds"]),
            "mtbf_text": _format_duration(m["mtbf_seconds"]),
            "currently_in_failure": m["currently_in_failure"],
        })
        total_failures += m["failure_count"]
        if m["mttr_seconds"] is not None:
            sum_mttr += m["mttr_seconds"]; n_mttr += 1
        if m["mtbf_seconds"] is not None:
            sum_mtbf += m["mtbf_seconds"]; n_mtbf += 1
        if m["availability_pct"] is not None:
            sum_avail += m["availability_pct"]; n_avail += 1
        if m["currently_in_failure"]:
            any_in_failure = True

    avg_mttr = sum_mttr / n_mttr if n_mttr else None
    avg_mtbf = sum_mtbf / n_mtbf if n_mtbf else None
    avg_avail = sum_avail / n_avail if n_avail else (100.0 if total_failures == 0 else None)

    return {
        "period": {
            "from": date_from.isoformat(),
            "to": date_to.isoformat(),
        },
        "summary": {
            "total_failures": total_failures,
            "avg_mttr_seconds": _round_or_none(avg_mttr, 1),
            "avg_mtbf_seconds": _round_or_none(avg_mtbf, 1),
            "avg_availability_pct": _round_or_none(avg_avail, 2),
            "avg_mttr_text": _format_duration(avg_mttr),
            "avg_mtbf_text": _format_duration(avg_mtbf),
            "any_robot_in_failure": any_in_failure,
            "robot_count": len(robots),
        },
        "robots": robots_data,
    }


@router.get("/utilization")
def api_utilization(
    date_from: datetime | None = Query(None, description="시작 (KST 기준, 미지정 시 7일 전)"),
    date_to: datetime | None = Query(None, description="종료 (KST 기준, 미지정 시 지금)"),
    robot_id: int | None = Query(None),
    db: Session = Depends(get_db),
):
    """가동률 지표 — 로봇별 status 점유 시간 비율 (대기/작업/충전/에러/오프라인).

    status 전이 사이의 구간을 status별로 적분.
    구간 = 다음 전이 시점 − 이전 전이 시점 (마지막 구간은 date_to까지).
    """
    if date_to is None:
        date_to = datetime.now(KST)
    if date_from is None:
        date_from = date_to - timedelta(days=7)

    q = db.query(Robot).filter(Robot.is_active == True)
    if robot_id:
        q = q.filter(Robot.id == robot_id)
    robots = q.order_by(Robot.id).all()
    robot_ids = [r.id for r in robots]

    history_q = (
        db.query(RobotStatusHistory.robot_id, RobotStatusHistory.recorded_at, RobotStatusHistory.status)
        .filter(RobotStatusHistory.robot_id.in_(robot_ids))
        .filter(RobotStatusHistory.recorded_at >= date_from)
        .filter(RobotStatusHistory.recorded_at <= date_to)
        .order_by(asc(RobotStatusHistory.robot_id), asc(RobotStatusHistory.recorded_at))
    )
    grouped: dict[int, list[tuple[datetime, int]]] = {rid: [] for rid in robot_ids}
    for rid, ts, st in history_q.all():
        grouped[rid].append((ts, st))

    status_labels = {0: "idle", 1: "working", 2: "charging", 3: "error", 4: "offline"}

    robots_data = []
    for r in robots:
        seq = grouped.get(r.id, [])
        durations = {0: 0.0, 1: 0.0, 2: 0.0, 3: 0.0, 4: 0.0}
        if seq:
            # 첫 전이 이전 시간 = 마지막 알려진 상태가 아니라 데이터 없음으로 처리
            for i, (ts, st) in enumerate(seq):
                next_ts = seq[i + 1][0] if i + 1 < len(seq) else date_to
                delta = max(0.0, (next_ts - ts).total_seconds())
                durations[st] = durations.get(st, 0.0) + delta

        total = sum(durations.values())
        ratios = {
            status_labels[k]: (v / total * 100 if total > 0 else 0.0)
            for k, v in durations.items()
        }
        ratios = {k: round(v, 2) for k, v in ratios.items()}

        robots_data.append({
            "robot_id": r.id,
            "robot_name": r.name,
            "wcs_label": f"AMR{r.wcs_no:02d}" if r.wcs_no else None,
            "total_seconds": round(total, 1),
            "durations_seconds": {status_labels[k]: round(v, 1) for k, v in durations.items()},
            "ratios_pct": ratios,
        })

    return {
        "period": {
            "from": date_from.isoformat(),
            "to": date_to.isoformat(),
        },
        "robots": robots_data,
    }
