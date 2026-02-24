from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.robot_api.robot_live_service import fetch_all_robots_live


from app.database import get_db
from app.schemas.robot import (
    RobotCreate,
    RobotUpdate,
    RobotResponse,
    RobotListResponse,
    RobotStatusUpdate,
    RobotStatusResponse,
    MinBatteryUpdate,
)
from app.crud.robot import (
    create_robot,
    get_robot,
    get_robots,
    update_robot,
    delete_robot,
    update_robot_status,
    get_robot_status,
    get_min_battery_by_sn,
    update_min_battery_by_sn,
)

router = APIRouter(prefix="/api/robots", tags=["로봇 관리"])


# ── 로봇 정보/Lits API 호출 ──
ROBOTS = [
    {"ip": "192.168.0.30", "secret": "19a11878aaab420fba94577ce3620dce"},
    {"ip": "192.168.0.31", "secret": "19a11878aaab420fba94577ce3620dce"},
    {"ip": "192.168.0.32", "secret": "19a11878aaab420fba94577ce3620dce"},
]

@router.get("/live")
def api_get_robots_live():
    return fetch_all_robots_live(ROBOTS)


@router.post("", response_model=RobotResponse, status_code=201)
def api_create_robot(data: RobotCreate, db: Session = Depends(get_db)):
    """RB-01 로봇 등록"""
    return create_robot(db, data)


@router.get("", response_model=RobotListResponse)
def api_get_robots(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    business_id: str | None = Query(None),
    db: Session = Depends(get_db),
):
    """로봇 목록 조회"""
    items = get_robots(db, skip=skip, limit=limit, business_id=business_id)
    return RobotListResponse(total=len(items), items=items)


# ── 최소 배터리 (SN 기반) ──

@router.get("/sn/{sn}/min-battery")
def api_get_min_battery(sn: str, db: Session = Depends(get_db)):
    """SN 기반 최소 배터리 조회"""
    return get_min_battery_by_sn(db, sn)


@router.patch("/sn/{sn}/min-battery")
def api_update_min_battery(sn: str, data: MinBatteryUpdate, db: Session = Depends(get_db)):
    """SN 기반 최소 배터리 수정"""
    return update_min_battery_by_sn(db, sn, data)


@router.get("/{robot_id}", response_model=RobotResponse)
def api_get_robot(robot_id: int, db: Session = Depends(get_db)):
    """로봇 단건 조회"""
    return get_robot(db, robot_id)


@router.put("/{robot_id}", response_model=RobotResponse)
def api_update_robot(robot_id: int, data: RobotUpdate, db: Session = Depends(get_db)):
    """RB-02 로봇 정보 수정"""
    return update_robot(db, robot_id, data)


@router.delete("/{robot_id}")
def api_delete_robot(robot_id: int, db: Session = Depends(get_db)):
    """RB-03 로봇 삭제 (Soft Delete)"""
    return delete_robot(db, robot_id)


# ── 로봇 상태 관련 ──

@router.get("/{robot_id}/status", response_model=RobotStatusResponse)
def api_get_robot_status(robot_id: int, db: Session = Depends(get_db)):
    """RB-05 로봇 상태 조회"""
    return get_robot_status(db, robot_id)


@router.put("/{robot_id}/status", response_model=RobotStatusResponse)
def api_update_robot_status(
    robot_id: int, data: RobotStatusUpdate, db: Session = Depends(get_db)
):
    """RB-04 로봇 상태 수집/업데이트
    ※ AutoXing SDK/API 연동 지점: 이 엔드포인트로 로봇 상태 데이터를 전송합니다.
    """
    return update_robot_status(db, robot_id, data)
