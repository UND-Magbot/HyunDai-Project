import logging

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

from app.crud.activity_log import log_activity

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/robots", tags=["로봇 관리"])


# ── 로봇 정보/Lits API 호출 ──
ROBOTS = [
    # {"ip": "192.168.10.42", "secret": "19a11878aaab420fba94577ce3620dce"},
    # {"ip": "192.168.10.44", "secret": "19a11878aaab420fba94577ce3620dce"},
    # {"ip": "192.168.10.46", "secret": "19a11878aaab420fba94577ce3620dce"},
    # {"ip": "192.168.10.212", "secret": "19a11878aaab420fba94577ce3620dce"},
    # {"ip": "192.168.10.73", "secret": "19a11878aaab420fba94577ce3620dce"},
    {"ip": "192.168.0.27", "secret": "19a11878aaab420fba94577ce3620dce"},
    {"ip": "192.168.0.30", "secret": "19a11878aaab420fba94577ce3620dce"},
    {"ip": "192.168.0.31", "secret": "19a11878aaab420fba94577ce3620dce"},
    {"ip": "192.168.0.33", "secret": "19a11878aaab420fba94577ce3620dce"},
    {"ip": "192.168.0.34", "secret": "19a11878aaab420fba94577ce3620dce"},
]

@router.get("/live")
def api_get_robots_live(db: Session = Depends(get_db)):
    """DB 로봇 목록을 기반으로 실시간 API 정보를 병합하여 반환.

    1차: DB robots 테이블에서 is_active인 로봇 목록
    2차: 실시간 API로 RUNSTATE, ONLINE, SIGNAL, POWER 등 오버레이
    3차: DB에 없지만 API에서 새로 발견된 로봇도 추가
    """
    # ── 1차: DB 로봇 목록 가져오기 ──
    db_robots = db.query(Robot).filter(Robot.is_active == True).all()

    # DB 로봇 → 기본 아이템 생성 (SN 기준 매핑)
    sn_to_item: dict[str, dict] = {}
    ip_to_sn: dict[str, str] = {}
    ip_to_robot_id: dict[str, int] = {}

    items = []
    for r in db_robots:
        item = {
            "ID": r.id,
            "IP": r.ip_address or "",
            "SN": r.serial_number,
            "ROBOTNAME": r.name,
            "MODEL": r.model or "-",
            "NICKNAME": None,
            "AXBOT_VERSION": None,
            "PLATFORM": None,
            "RUNSTATE": "OFFLINE",
            "ONLINE": "Offline",
            "SIGNAL": "N/A",
            "POWER(%)": "-",
        }
        items.append(item)
        sn_to_item[r.serial_number] = item
        if r.ip_address:
            ip_to_sn[r.ip_address] = r.serial_number
            ip_to_robot_id[r.ip_address] = r.id

    # ── 2차: 실시간 API로 상태 오버레이 ──
    live = fetch_all_robots_live(ROBOTS)
    CHARGING_STATUSES = {"charging", "charging_route", "low_battery_charging"}

    for live_item in live.get("items", []):
        live_ip = live_item.get("IP", "")
        live_sn = live_item.get("SN", "")

        # IP로 DB 로봇 매칭
        matched_sn = ip_to_sn.get(live_ip)
        # SN으로도 매칭 시도
        if not matched_sn and live_sn and live_sn != "N/A":
            matched_sn = live_sn if live_sn in sn_to_item else None

        if matched_sn and matched_sn in sn_to_item:
            # DB에 있는 로봇 → 실시간 정보 오버레이
            target = sn_to_item[matched_sn]
            if live_item.get("ROBOTNAME") and live_item["ROBOTNAME"] != "N/A":
                target["ROBOTNAME"] = live_item["ROBOTNAME"]
            if live_item.get("MODEL") and live_item["MODEL"] != "N/A":
                target["MODEL"] = live_item["MODEL"]
            target["NICKNAME"] = live_item.get("NICKNAME")
            target["AXBOT_VERSION"] = live_item.get("AXBOT_VERSION")
            target["PLATFORM"] = live_item.get("PLATFORM")
            target["RUNSTATE"] = live_item.get("RUNSTATE", "OFFLINE")
            target["ONLINE"] = live_item.get("ONLINE", "Offline")
            target["SIGNAL"] = live_item.get("SIGNAL", "N/A")
            target["POWER(%)"] = live_item.get("POWER(%)", "-")
            if not target["IP"] and live_ip:
                target["IP"] = live_ip

            # CHARGING 오버라이드
            robot_id = ip_to_robot_id.get(live_ip)
            if robot_id is not None and target["RUNSTATE"] == "EXECUTING":
                task_status = get_loop_status(robot_id).get("status", "")
                if task_status in CHARGING_STATUSES:
                    target["RUNSTATE"] = "CHARGING"
        else:
            # DB에 없는 새 로봇 → 리스트에 추가
            if live_sn and live_sn != "N/A":
                new_item = {
                    "ID": None,
                    "IP": live_ip,
                    "SN": live_sn,
                    "ROBOTNAME": live_item.get("ROBOTNAME", live_sn),
                    "MODEL": live_item.get("MODEL", "-"),
                    "NICKNAME": live_item.get("NICKNAME"),
                    "AXBOT_VERSION": live_item.get("AXBOT_VERSION"),
                    "PLATFORM": live_item.get("PLATFORM"),
                    "RUNSTATE": live_item.get("RUNSTATE", "OFFLINE"),
                    "ONLINE": live_item.get("ONLINE", "Offline"),
                    "SIGNAL": live_item.get("SIGNAL", "N/A"),
                    "POWER(%)": live_item.get("POWER(%)", "-"),
                }
                items.append(new_item)
                sn_to_item[live_sn] = new_item

    items.sort(key=lambda x: str(x.get("IP", "")))
    return {"total": len(items), "items": items}


@router.post("/sync-live")
def api_sync_live_robots(db: Session = Depends(get_db)):
    """라이브 로봇 정보를 DB robots 테이블에 동기화 (upsert by serial_number)"""
    live = fetch_all_robots_live(ROBOTS)
    items = live.get("items", [])

    created = 0
    updated = 0
    skipped = 0
    synced = []

    for item in items:
        sn = item.get("SN", "")
        if not sn or sn == "N/A":
            skipped += 1
            continue

        ip = item.get("IP", "")
        name = item.get("ROBOTNAME", "") or sn
        model = item.get("MODEL", "")

        existing = db.query(Robot).filter(Robot.serial_number == sn).first()

        if existing:
            if name and name != "N/A":
                existing.name = name
            if model and model != "N/A":
                existing.model = model
            if ip:
                existing.ip_address = ip
            existing.is_active = True
            updated += 1
            synced.append({"sn": sn, "name": name, "action": "updated"})
        else:
            new_robot = Robot(
                name=name if name and name != "N/A" else sn,
                serial_number=sn,
                model=model if model and model != "N/A" else None,
                ip_address=ip or None,
            )
            db.add(new_robot)
            created += 1
            synced.append({"sn": sn, "name": name, "action": "created"})

    db.commit()
    logger.info(f"sync-live: created={created}, updated={updated}, skipped={skipped}")
    log_activity("robot", "robot_sync",
                 f"로봇 동기화 완료: 생성 {created}, 갱신 {updated}, 건너뜀 {skipped}",
                 source="api_sync_live_robots")

    return {
        "message": f"동기화 완료: 생성 {created}, 갱신 {updated}, 건너뜀 {skipped}",
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "synced": synced,
    }


@router.post("", response_model=RobotResponse, status_code=201)
def api_create_robot(data: RobotCreate, db: Session = Depends(get_db)):
    """RB-01 로봇 등록"""
    result = create_robot(db, data)
    log_activity("robot", "robot_create",
                 f"로봇 등록: {data.name} (SN: {data.serial_number})",
                 source="api_create_robot")
    return result


@router.get("", response_model=RobotListResponse)
def api_get_robots(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    business_id: str | None = Query(None),
    area_id: str | None = Query(None),
    db: Session = Depends(get_db),
):
    """로봇 목록 조회"""
    items = get_robots(db, skip=skip, limit=limit, business_id=business_id, area_id=area_id)
    return RobotListResponse(total=len(items), items=items)


# ── 최소 배터리 (SN 기반) ──

@router.get("/sn/{sn}/min-battery")
def api_get_min_battery(sn: str, db: Session = Depends(get_db)):
    """SN 기반 최소 배터리 조회"""
    return get_min_battery_by_sn(db, sn)


@router.patch("/sn/{sn}/min-battery")
def api_update_min_battery(sn: str, data: MinBatteryUpdate, db: Session = Depends(get_db)):
    """SN 기반 최소 배터리 수정"""
    result = update_min_battery_by_sn(db, sn, data)
    changes = [f"최소배터리={data.min_battery}%"]
    if data.charging_id is not None:
        changes.append(f"충전소 변경(ID={data.charging_id})")
    if data.standby_id is not None:
        changes.append(f"귀환장소 변경(ID={data.standby_id})")
    log_activity("robot", "battery_setting",
                 f"로봇 {sn} 설정 변경 — {', '.join(changes)}",
                 source="api_update_min_battery")
    return result


@router.get("/sn/{sn}/charging-pois")
def api_get_charging_pois(sn: str, db: Session = Depends(get_db)):
    """SN 기반 충전소 POI 조회 — 로봇이 속한 영역의 맵에서 충전소 검색.
    area_id가 없으면 전체 활성 맵에서 충전소를 검색한다.
    """
    robot = db.query(Robot).filter(Robot.serial_number == sn, Robot.is_active == True).first()
    if not robot:
        return []

    # area_id가 있으면 해당 영역의 맵만, 없으면 전체 활성 맵
    if robot.area_id:
        try:
            area_id = int(robot.area_id)
        except (ValueError, TypeError):
            area_id = None
    else:
        area_id = None

    if area_id is not None:
        maps = (
            db.query(RobotMap)
            .filter(RobotMap.area_id == area_id, RobotMap.is_active == True)
            .all()
        )
    else:
        maps = db.query(RobotMap).filter(RobotMap.is_active == True).all()

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


@router.get("/sn/{sn}/standby-pois")
def api_get_standby_pois(sn: str, db: Session = Depends(get_db)):
    """SN 기반 대기장소 POI 조회 — 전체 활성 맵에서 standby 타입 POI 검색"""
    robot = db.query(Robot).filter(Robot.serial_number == sn, Robot.is_active == True).first()
    if not robot:
        return []

    if robot.area_id:
        try:
            area_id = int(robot.area_id)
        except (ValueError, TypeError):
            area_id = None
    else:
        area_id = None

    if area_id is not None:
        maps = (
            db.query(RobotMap)
            .filter(RobotMap.area_id == area_id, RobotMap.is_active == True)
            .all()
        )
    else:
        maps = db.query(RobotMap).filter(RobotMap.is_active == True).all()

    if not maps:
        return []

    result = []
    for m in maps:
        pois = (
            db.query(MapPOI)
            .filter(
                MapPOI.map_id == m.id,
                MapPOI.poi_type == "standby",
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
    result = update_robot(db, robot_id, data)
    log_activity("robot", "robot_update",
                 f"로봇 정보 수정: {result.name} (SN: {result.serial_number})",
                 robot_id=robot_id, source="api_update_robot")
    return result


@router.delete("/{robot_id}")
def api_delete_robot(robot_id: int, db: Session = Depends(get_db)):
    """RB-03 로봇 삭제 (Soft Delete)"""
    robot = db.query(Robot).filter(Robot.id == robot_id).first()
    robot_label = f"{robot.name} (SN: {robot.serial_number})" if robot else f"ID:{robot_id}"
    result = delete_robot(db, robot_id)
    log_activity("robot", "robot_delete",
                 f"로봇 삭제: {robot_label}",
                 robot_id=robot_id, source="api_delete_robot")
    return result


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
