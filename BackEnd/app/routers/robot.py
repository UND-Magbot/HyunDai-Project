from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.robot_api.robot_live_service import fetch_all_robots_live
from app.robot_api.robot_task_service import get_loop_status

from app.database import get_db
from app.models.robot import Robot
from app.models.map import RobotMap, MapPOI
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
def api_get_robots_live(db: Session = Depends(get_db)):
    result = fetch_all_robots_live(ROBOTS)

    # 작업 서비스 상태가 충전 관련이면 RUNSTATE를 CHARGING으로 오버라이드
    # (로봇이 충전소로 이동 중일 때 move_state=moving → EXECUTING 반환 문제 해결)
    CHARGING_STATUSES = {"charging", "charging_route", "low_battery_charging"}
    ip_to_robot_id: dict[str, int] = {}
    robots = db.query(Robot).filter(Robot.is_active == True, Robot.ip_address.isnot(None)).all()
    for r in robots:
        ip_to_robot_id[r.ip_address] = r.id

    for item in result.get("items", []):
        robot_id = ip_to_robot_id.get(item.get("IP"))
        if robot_id is not None and item.get("RUNSTATE") == "EXECUTING":
            task_status = get_loop_status(robot_id).get("status", "")
            if task_status in CHARGING_STATUSES:
                item["RUNSTATE"] = "CHARGING"

    return result


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


@router.get("/sn/{sn}/charging-pois")
def api_get_charging_pois(sn: str, db: Session = Depends(get_db)):
    """SN 기반 충전소 POI 조회 — 로봇이 속한 영역의 맵에서 충전소 검색"""
    robot = db.query(Robot).filter(Robot.serial_number == sn, Robot.is_active == True).first()
    if not robot or not robot.area_id:
        return []

    try:
        area_id = int(robot.area_id)
    except (ValueError, TypeError):
        return []

    maps = (
        db.query(RobotMap)
        .filter(RobotMap.area_id == area_id, RobotMap.is_active == True)
        .all()
    )
    if not maps:
        return []

    result = []
    for m in maps:
        pois = (
            db.query(MapPOI)
            .filter(
                MapPOI.map_id == m.id,
                MapPOI.poi_type == "charging",
                MapPOI.is_active == True,
            )
            .all()
        )
        for poi in pois:
            result.append({"id": poi.id, "name": poi.name})

    return result


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
