import json
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)
from typing import Optional
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.robot import Robot
from app.models.map import MapPOI, ConvoyConfig, ConvoySavedState
from app.robot_api.robot_convoy_service import start_convoy, start_convoy_resume, stop_convoy, force_stop_convoy, get_convoy_status, fire_evacuate, reset_fire, return_all_convoy
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
    reset_time: Optional[str] = None
    battery_check_interval: Optional[int] = None  # 배터리 체크 주기 (분, 5~120)


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

def _build_auto_robots_config(db: Session) -> list[dict]:
    """활성 로봇 + 출발지 설정된 로봇을 convoy 대상으로 자동 구성"""
    robots = db.query(Robot).filter(
        Robot.is_active == True,
        (Robot.charging_id.isnot(None)) | (Robot.standby_id.isnot(None)),
    ).all()
    result = []
    for r in robots:
        poi_id = r.charging_id or r.standby_id
        poi = db.query(MapPOI).filter(MapPOI.id == poi_id, MapPOI.is_active == True).first()
        if not poi:
            continue
        result.append({
            "robot_id": r.id,
            "charging_poi": poi.name,
            "entry_poi_names": [f"{poi.name}-1", "ENTER-LAST"],
            "return_poi_names": ["ENTER-LAST", f"{poi.name}-1"],
        })
    return result


@router.get("/config")
def api_convoy_config(db: Session = Depends(get_db)):
    """Convoy 작업 설정 조회
    - work_poi_names / stop_names: DB convoy_configs 테이블
    - robots_config: DB의 활성 로봇에서 실시간 자동 추출 (JSON 필드 사용 안 함)
    """
    cfg = db.query(ConvoyConfig).filter(ConvoyConfig.is_active == True).first()

    if cfg:
        return {
            "work_poi_names": json.loads(cfg.work_poi_names),
            "stop_names": json.loads(cfg.stop_names),
            "robots_config": _build_auto_robots_config(db),
            "reset_time": cfg.reset_time or "08:00",
            "battery_check_interval": cfg.battery_check_interval or 5,
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
    if req.reset_time is not None:
        cfg.reset_time = req.reset_time
    if req.battery_check_interval is not None:
        cfg.battery_check_interval = max(5, min(120, req.battery_check_interval))

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
def api_convoy_start(fresh: bool = False, immediate: bool = False, db: Session = Depends(get_db)):
    """Convoy 대열 작업 시작
    - fresh=true → 저장 상태 무시, 처음부터 시작
    - immediate=true → 현재 위치에서 바로 재개 (비상정지 후 다시 시작)
    - 리셋 시각 이내 저장 상태가 있으면 → 저장 위치에서 재개 (먼 노드부터 출발)
    - 없으면 → 처음부터 시작 (기존 로직)
    """
    cfg = _load_config(db)

    work_poi_names = json.loads(cfg.work_poi_names)
    stop_names = json.loads(cfg.stop_names)

    # ── convoy 대상 로봇 자동 추출 ──
    # is_active=TRUE 이고 (charging_id 또는 standby_id 설정된) 로봇을 자동으로 포함.
    # robots_config JSON은 사용하지 않음 → 스페어 교체 시 UI 드롭다운만 수정하면 됨.
    auto_robots = db.query(Robot).filter(
        Robot.is_active == True,
        (Robot.charging_id.isnot(None)) | (Robot.standby_id.isnot(None)),
    ).all()
    robots_cfg = [{"robot_id": r.id} for r in auto_robots]

    if not work_poi_names:
        raise HTTPException(status_code=400, detail="work_poi_names가 비어있습니다")
    if not robots_cfg:
        raise HTTPException(
            status_code=400,
            detail="활성 로봇이 없습니다 — is_active=TRUE이고 charging_id 또는 standby_id가 설정된 로봇이 최소 1대 필요합니다",
        )

    # ── 리셋 시각 기준 저장 상태 확인 ──
    if fresh:
        # 강제 신규 시작: 저장 상태 전체 삭제
        del_count = db.query(ConvoySavedState).delete()
        if del_count:
            db.commit()
            logger.info(f"[Convoy] 신규 시작 — 저장 상태 {del_count}건 삭제")
        saved_map: dict = {}
    else:
        reset_time_str = cfg.reset_time or "08:00"
        try:
            rh, rm = map(int, reset_time_str.split(":"))
        except (ValueError, AttributeError):
            rh, rm = 8, 0

        # DB 서버 시간 기준으로 cutoff 계산 (Python↔DB 시간대 불일치 방지)
        from sqlalchemy import func as sa_func, text
        db_now = db.execute(text("SELECT NOW()")).scalar()
        now = db_now if db_now else datetime.now()

        today_reset = now.replace(hour=rh, minute=rm, second=0, microsecond=0)
        # 현재가 리셋 시각 이전이면 전날 리셋 시각 기준
        cutoff = today_reset if now >= today_reset else today_reset - timedelta(days=1)

        logger.info(f"[Convoy] 리셋 체크 — DB시각={now}, cutoff={cutoff}")

        # 리셋 시각 이전 저장 상태 삭제
        old_count = db.query(ConvoySavedState).filter(
            ConvoySavedState.saved_at < cutoff
        ).delete()
        if old_count:
            logger.info(f"[Convoy] 만료 저장 상태 {old_count}건 삭제")
            db.commit()

        saved_states = db.query(ConvoySavedState).filter(
            ConvoySavedState.saved_at >= cutoff
        ).all()
        saved_map = {s.robot_id: s for s in saved_states}  # {robot_id: ConvoySavedState}

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

        # 허용된 출발지만 참여 (W1, W2, C1, C2, C3)
        ALLOWED_START_POIS = {"W1", "W2", "C1", "C2", "C3"}
        if start_poi_name not in ALLOWED_START_POIS:
            continue

        # 경로 자동 생성: {POI}-1 → ENTER-LAST
        entry_names = [f"{start_poi_name}-1", "ENTER-LAST"]
        return_names = ["ENTER-LAST", f"{start_poi_name}-1"]

        robot_display = f"AMR{robot.wcs_no:02d}" if robot.wcs_no else f"로봇 {rid}"
        rc_item = {
            "robot_id": rid,
            "ip": robot.ip_address,
            "entry_poi_names": entry_names,
            "return_poi_names": return_names,
            "charging_poi_name": start_poi_name if start_poi_type == "charging" else None,
            "standby_poi_name": start_poi_name if start_poi_type == "standby" else None,
            "start_poi_type": start_poi_type,
            "_start_poi_name": start_poi_name,
            "robot_name": robot_display,
        }

        # 저장 상태가 있고 실좌표가 있으면 resume 정보 추가
        if rid in saved_map and saved_map[rid].actual_x is not None:
            ss = saved_map[rid]
            rc_item["resume_node_index"] = ss.node_index
            rc_item["resume_work_poi_name"] = ss.work_poi_name
            rc_item["resume_actual_x"] = ss.actual_x
            rc_item["resume_actual_y"] = ss.actual_y
            rc_item["resume_actual_ori"] = ss.actual_ori

        robots_config.append(rc_item)

    # 재개 모드일 때, 저장 안 된 로봇은 WORK1(node_index=0)로 시작
    has_resume = any("resume_node_index" in rc for rc in robots_config)
    if has_resume:
        from app.robot_api.robot_task_service import _get_battery_percentage
        for rc_item in robots_config:
            if "resume_node_index" not in rc_item:
                rc_item["resume_node_index"] = 0
                rc_item["resume_work_poi_name"] = work_poi_names[0] if work_poi_names else "WORK1"
                # 배터리 조회 (저장 안 된 로봇 정렬용)
                batt = _get_battery_percentage(rc_item["ip"])
                rc_item["_battery"] = batt if batt is not None else 0.0

    if not robots_config:
        raise HTTPException(status_code=400, detail="출발 가능한 로봇이 없습니다 (충전소/대기지점 미지정)")

    # ── 재개 모드 vs 신규 시작 분기 (위에서 이미 판단됨) ──

    if has_resume:
        # 저장된 로봇: node_index 큰 순, 저장 안 된 로봇: 배터리 높은 순
        def _resume_sort_key(rc):
            has_saved = rc.get("resume_actual_x") is not None
            node = rc.get("resume_node_index", -1)
            batt = rc.get("_battery", 0.0)
            # 저장된 로봇 우선 (1), 그 안에서 node_index 큰 순
            # 저장 안 된 로봇 (0), 그 안에서 배터리 높은 순
            return (1 if has_saved else 0, node, batt)

        robots_config.sort(key=_resume_sort_key, reverse=True)

        # _battery 임시 키 정리 + immediate 플래그 전달
        for rc in robots_config:
            rc.pop("_battery", None)
            if immediate:
                rc["immediate_resume"] = True

        active_robots = robots_config[:4]
        standby_robots = robots_config[4:]

        for rc in active_robots + standby_robots:
            rc.pop("_start_poi_name", None)

        ok, msg = start_convoy_resume(active_robots, work_poi_names, stop_names, standby_robots)
        # 재개 모드: 저장 상태 유지 (정지 시 갱신됨, 24시간 경과 시 자동 무효)
    else:
        # 신규 시작: 기존 출발 순서 정렬
        _DEPARTURE_ORDER = {"C1": 0, "C2": 1, "C3": 2, "W1": 3, "W2": 4}

        def _departure_order(rc):
            name = rc["_start_poi_name"]
            return (_DEPARTURE_ORDER.get(name, 99), name)

        robots_config.sort(key=_departure_order)

        active_robots = robots_config[:4]
        standby_robots = robots_config[4:]

        for rc in active_robots + standby_robots:
            rc.pop("_start_poi_name", None)

        ok, msg = start_convoy(active_robots, work_poi_names, stop_names, standby_robots)

        # 신규 시작 시 기존 저장 상태 정리
        db.query(ConvoySavedState).delete()
        db.commit()

    if not ok:
        raise HTTPException(status_code=400, detail=msg)

    return {
        "message": msg,
        "mode": "resume" if has_resume else "fresh",
        "active_robots": [
            {"robot_id": rc["robot_id"],
             "start_poi_type": rc["start_poi_type"],
             "entry": rc["entry_poi_names"],
             **({"resume_node": rc["resume_node_index"]} if "resume_node_index" in rc else {})}
            for rc in active_robots
        ],
        "standby_robots": [
            {"robot_id": rc["robot_id"],
             "start_poi_type": rc["start_poi_type"]}
            for rc in standby_robots
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


@router.post("/fire-test")
def api_fire_test():
    """[테스트] 화재 경보 발령 → convoy 로봇 SAFE 대피"""
    ok, msg = fire_evacuate()
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"message": msg}


@router.post("/fire-reset")
def api_fire_reset():
    """[테스트] 화재 해제 → convoy 상태 초기화"""
    reset_fire()
    return {"message": "화재 해제 완료"}


@router.post("/return-all")
def api_convoy_return_all():
    """비상정지 후 전체 복귀 — 로봇을 1대씩 7초 간격으로 충전소/대기지점으로 복귀"""
    ok, msg = return_all_convoy(interval=15.0)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"message": msg}


@router.post("/pause")
def api_convoy_pause(db: Session = Depends(get_db)):
    """전체 일시정지 — 모든 로봇 manual 모드 전환 (즉시 멈춤)"""
    import requests as http_req
    _auto = db.query(Robot).filter(
        Robot.is_active == True,
        (Robot.charging_id.isnot(None)) | (Robot.standby_id.isnot(None)),
    ).all()
    robots_cfg = [{"robot_id": r.id} for r in _auto]
    secret = "19a11878aaab420fba94577ce3620dce"
    results = []
    ok_count = 0
    fail_count = 0
    for rc in robots_cfg:
        robot = db.query(Robot).filter(Robot.id == rc["robot_id"], Robot.is_active == True).first()
        if not robot or not robot.ip_address:
            continue
        try:
            r = http_req.post(
                f"http://{robot.ip_address}:8090/services/wheel_control/set_control_mode",
                headers={"Authorization": f"Secret {secret}", "Content-Type": "application/json"},
                json={"control_mode": "manual"}, timeout=5)
            results.append({"robot_id": rc["robot_id"], "status": r.status_code})
            if 200 <= r.status_code < 300:
                ok_count += 1
            else:
                fail_count += 1
        except Exception as e:
            results.append({"robot_id": rc["robot_id"], "error": str(e)})
            fail_count += 1

    log_activity("convoy", "convoy_pause",
                 f"Convoy 전체 일시정지 — 성공 {ok_count}대 / 실패 {fail_count}대",
                 source="api_convoy_pause")
    return {"message": "전체 일시정지 완료", "results": results}


@router.post("/resume")
def api_convoy_resume(db: Session = Depends(get_db)):
    """전체 일시정지 해제 — 모든 로봇 auto 모드 복원 (이동 재개)"""
    import requests as http_req
    _auto = db.query(Robot).filter(
        Robot.is_active == True,
        (Robot.charging_id.isnot(None)) | (Robot.standby_id.isnot(None)),
    ).all()
    robots_cfg = [{"robot_id": r.id} for r in _auto]
    secret = "19a11878aaab420fba94577ce3620dce"
    results = []
    ok_count = 0
    fail_count = 0
    for rc in robots_cfg:
        robot = db.query(Robot).filter(Robot.id == rc["robot_id"], Robot.is_active == True).first()
        if not robot or not robot.ip_address:
            continue
        try:
            r = http_req.post(
                f"http://{robot.ip_address}:8090/services/wheel_control/set_control_mode",
                headers={"Authorization": f"Secret {secret}", "Content-Type": "application/json"},
                json={"control_mode": "auto"}, timeout=5)
            results.append({"robot_id": rc["robot_id"], "status": r.status_code})
            if 200 <= r.status_code < 300:
                ok_count += 1
            else:
                fail_count += 1
        except Exception as e:
            results.append({"robot_id": rc["robot_id"], "error": str(e)})
            fail_count += 1

    log_activity("convoy", "convoy_resume",
                 f"Convoy 일시정지 해제 — 성공 {ok_count}대 / 실패 {fail_count}대",
                 source="api_convoy_resume")
    return {"message": "전체 일시정지 해제 완료", "results": results}
