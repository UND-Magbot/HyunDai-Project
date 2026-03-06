import json
from typing import Optional
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.robot import Robot
from app.models.map import MapPOI, ConvoyConfig
from app.robot_api.robot_convoy_service import start_convoy, stop_convoy, force_stop_convoy, get_convoy_status
from app.robot_api.robot_task_service import confirm_loop
from app.robot_api.route_utils import find_work_loop_order
from app.crud.activity_log import log_activity

router = APIRouter(prefix="/api/convoy", tags=["Convoy 대열 작업"])


# ─── 요청 스키마 ───────────────────────────────────────────────────────────────

class RobotConfigItem(BaseModel):
    robot_id: int
    charging_poi: str
    entry_poi_names: list[str]
    return_poi_names: list[str]


class ConvoyConfigUpdate(BaseModel):
    work_poi_names: Optional[list[str]] = None
    stop_names: Optional[list[str]] = None
    robots_config: Optional[list[RobotConfigItem]] = None


# ─── 헬퍼 ─────────────────────────────────────────────────────────────────────

def _get_robot(db: Session, robot_id: int) -> Robot:
    robot = db.query(Robot).filter(Robot.id == robot_id, Robot.is_active == True).first()
    if not robot:
        raise HTTPException(status_code=404, detail=f"로봇 {robot_id}을 찾을 수 없습니다")
    if not robot.ip_address:
        raise HTTPException(status_code=400, detail=f"로봇 {robot_id} IP 주소가 등록되지 않았습니다")
    return robot


def _load_config(db: Session) -> ConvoyConfig:
    cfg = db.query(ConvoyConfig).filter(ConvoyConfig.is_active == True).first()
    if not cfg:
        raise HTTPException(status_code=404, detail="Convoy 설정이 없습니다. PUT /api/convoy/config로 설정하세요")
    return cfg


# ─── 엔드포인트 ────────────────────────────────────────────────────────────────

@router.get("/config")
def api_convoy_config(db: Session = Depends(get_db)):
    """Convoy 작업 설정 조회
    1순위: DB convoy_configs 테이블
    2순위: MapLine 그래프에서 자동 결정 (폴백)
    """
    cfg = db.query(ConvoyConfig).filter(ConvoyConfig.is_active == True).first()

    if cfg:
        return {
            "work_poi_names": json.loads(cfg.work_poi_names),
            "stop_names": json.loads(cfg.stop_names),
            "robots_config": json.loads(cfg.robots_config),
        }

    # DB 설정 없으면 그래프 탐색 폴백 (최신 활성 맵 기준)
    from app.models.map import RobotMap
    work1 = db.query(MapPOI).join(RobotMap).filter(
        MapPOI.name == "WORK1", MapPOI.is_active == True,
        RobotMap.is_active == True,
    ).order_by(RobotMap.id.desc()).first()

    if not work1:
        raise HTTPException(status_code=404, detail="WORK1 POI를 찾을 수 없습니다")

    work_poi_names = find_work_loop_order(db, work1.map_id)

    return {
        "work_poi_names": work_poi_names,
        "stop_names": [],
        "robots_config": [],
    }


@router.put("/config")
def api_convoy_config_update(req: ConvoyConfigUpdate, db: Session = Depends(get_db)):
    """Convoy 작업 설정 저장/수정"""
    cfg = db.query(ConvoyConfig).filter(ConvoyConfig.is_active == True).first()

    if not cfg:
        cfg = ConvoyConfig(
            name="default",
            work_poi_names="[]",
            stop_names="[]",
            robots_config="[]",
        )
        db.add(cfg)

    if req.work_poi_names is not None:
        cfg.work_poi_names = json.dumps(req.work_poi_names)
    if req.stop_names is not None:
        cfg.stop_names = json.dumps(req.stop_names)
    if req.robots_config is not None:
        cfg.robots_config = json.dumps([r.model_dump() for r in req.robots_config])

    db.commit()
    db.refresh(cfg)
    log_activity("convoy", "convoy_config",
                 "Convoy 설정 변경",
                 source="api_convoy_config_update")

    return {
        "work_poi_names": json.loads(cfg.work_poi_names),
        "stop_names": json.loads(cfg.stop_names),
        "robots_config": json.loads(cfg.robots_config),
    }


@router.post("/start")
def api_convoy_start(db: Session = Depends(get_db)):
    """Convoy 대열 작업 시작 — DB config에서 설정을 읽고,
    각 로봇의 standby_id/charging_id에서 진입/복귀 경로를 자동 생성하여 실행.
    """
    cfg = _load_config(db)

    work_poi_names = json.loads(cfg.work_poi_names)
    stop_names = json.loads(cfg.stop_names)
    robots_cfg = json.loads(cfg.robots_config)

    if not work_poi_names:
        raise HTTPException(status_code=400, detail="work_poi_names가 비어있습니다")
    if not robots_cfg:
        raise HTTPException(status_code=400, detail="robots_config가 비어있습니다")

    robots_config = []
    for rcfg in robots_cfg:
        rid = rcfg["robot_id"]
        robot = _get_robot(db, rid)

        # ── 시작 위치 자동 감지 (standby 우선) ──
        start_poi_name = None
        start_poi_type = None  # "charging" | "standby"

        if robot.standby_id:
            poi = db.query(MapPOI).filter(
                MapPOI.id == robot.standby_id, MapPOI.is_active == True
            ).first()
            if poi:
                start_poi_name = poi.name
                start_poi_type = "standby"

        if not start_poi_name and robot.charging_id:
            poi = db.query(MapPOI).filter(
                MapPOI.id == robot.charging_id, MapPOI.is_active == True
            ).first()
            if poi:
                start_poi_name = poi.name
                start_poi_type = "charging"

        if not start_poi_name:
            # 충전소/대기지점 미지정 로봇은 건너뜀
            continue

        # 허용된 출발지만 참여 (W1, C1, C2, C3)
        ALLOWED_START_POIS = {"W1", "C1", "C2", "C3"}
        if start_poi_name not in ALLOWED_START_POIS:
            continue

        # 경로 자동 생성: {POI}-1 → ENTER-LAST
        entry_names = [f"{start_poi_name}-1", "ENTER-LAST"]
        return_names = ["ENTER-LAST", f"{start_poi_name}-1"]

        robots_config.append({
            "robot_id": rid,
            "ip": robot.ip_address,
            "entry_poi_names": entry_names,
            "return_poi_names": return_names,
            "charging_poi_name": start_poi_name if start_poi_type == "charging" else None,
            "standby_poi_name": start_poi_name if start_poi_type == "standby" else None,
            "start_poi_type": start_poi_type,
            "_start_poi_name": start_poi_name,
        })

    if not robots_config:
        raise HTTPException(status_code=400, detail="출발 가능한 로봇이 없습니다 (충전소/대기지점 미지정)")

    # ── 출발 순서 정렬: W(대기지점) → C(충전소), 번호 오름차순 ──
    def _departure_order(rc):
        name = rc["_start_poi_name"]
        # W → 0, C → 1, 기타 → 2 (대기지점 우선)
        prefix_order = 0 if name.startswith("W") else (1 if name.startswith("C") else 2)
        return (prefix_order, name)

    robots_config.sort(key=_departure_order)

    # 정렬 후 내부 키 제거
    for rc in robots_config:
        rc.pop("_start_poi_name", None)

    ok, msg = start_convoy(robots_config, work_poi_names, stop_names)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)

    return {
        "message": msg,
        "robots": [
            {"robot_id": rc["robot_id"],
             "start_poi_type": rc["start_poi_type"],
             "entry": rc["entry_poi_names"],
             "return": rc["return_poi_names"]}
            for rc in robots_config
        ],
    }


@router.post("/stop")
def api_convoy_stop():
    """Convoy 그레이스풀 정지 — 현재 루프 완주 → WORK1 복귀 → 역순 경로 귀환"""
    ok, msg = stop_convoy()
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"message": msg}


@router.post("/force-stop")
def api_convoy_force_stop():
    """Convoy 즉시 정지 — 모든 이동 취소 + 상태 리셋"""
    ok, msg = force_stop_convoy()
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"message": msg}


@router.get("/status")
def api_convoy_status():
    """Convoy 전체 상태 조회"""
    return get_convoy_status()


@router.post("/confirm/{robot_id}")
def api_convoy_confirm(robot_id: int):
    """작업 포인트 태블릿 확인 (기존 confirm_loop 재사용)"""
    ok, msg = confirm_loop(robot_id)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"message": msg, "robot_id": robot_id}
