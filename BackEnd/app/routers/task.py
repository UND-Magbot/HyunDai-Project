from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.robot import Robot
from app.models.map import MapPOI
from app.robot_api.robot_task_service import start_loop, stop_loop, get_loop_status, confirm_loop, send_charge, start_charge_route, start_return_route, cancel_current_move
from app.robot_api.robot_live_service import _collect_ws_topics, _to_runstate
from app.robot_api.route_utils import find_route
from app.crud.activity_log import log_activity

router = APIRouter(prefix="/api/tasks", tags=["작업 관리"])


# ─── 요청 스키마 ───────────────────────────────────────────────────────────────

class LoopStartRequest(BaseModel):
    robot_id: int
    poi_names: list[str] = Field(..., min_length=1, description="순서대로 방문할 POI 이름 목록")
    stop_names: list[str] = Field(default=[], description="작업 포인트 (정지할 POI 이름). 비어있으면 모든 POI에서 정지")
    entry_poi_names: list[str] = Field(default=[], description="진입 경로 POI (충전소→작업구역, 최초 1회만 통과)")


# ─── 헬퍼 ─────────────────────────────────────────────────────────────────────

def _get_robot_ip(db: Session, robot_id: int) -> str | JSONResponse:
    robot = db.query(Robot).filter(Robot.id == robot_id, Robot.is_active == True).first()
    if not robot:
        return JSONResponse(status_code=404, content={"detail": "로봇을 찾지 못했습니다."})
    if not robot.ip_address:
        return JSONResponse(status_code=400, content={
            "detail": "로봇 IP 주소가 등록되어 있지 않습니다.", "error_code": "ROBOT-003",
            "description": "_get_robot_ip() — IP 미등록"
        })
    return robot.ip_address


# ─── 엔드포인트 ────────────────────────────────────────────────────────────────

@router.post("/loop/start")
def api_start_loop(req: LoopStartRequest, db: Session = Depends(get_db)):
    """무한반복 작업 시작
    - poi_names: DB map_pois 테이블의 POI name 목록 (순서대로 방문)
    - 예시: ["CUR-001", "CUR-002"]
    """
    ip = _get_robot_ip(db, req.robot_id)
    if isinstance(ip, JSONResponse):
        return ip

    # is_running 체크는 start_loop 내부에서 처리 (정리 로직 포함)
    ok, msg, code = start_loop(req.robot_id, ip, req.poi_names, req.stop_names, req.entry_poi_names)
    if not ok:
        desc_map = {"TASK-001": "start_loop() — 이미 작업 실행 중일 때", "TASK-002": "start_loop() — POI 없이 작업 시작"}
        return JSONResponse(status_code=400, content={"detail": msg, "error_code": code, "description": desc_map.get(code, "")})

    return {"message": msg, "robot_id": req.robot_id, "poi_names": req.poi_names, "stop_names": req.stop_names, "entry_poi_names": req.entry_poi_names}


@router.post("/loop/stop/{robot_id}")
def api_stop_loop(robot_id: int, db: Session = Depends(get_db)):
    """무한반복 작업 정지"""
    ip = _get_robot_ip(db, robot_id)
    if isinstance(ip, JSONResponse):
        return ip
    ok, msg, code = stop_loop(robot_id, ip)
    if not ok:
        return JSONResponse(status_code=400, content={"detail": msg, "error_code": code, "description": "stop_loop() — 정지할 작업 없음"})

    return {"message": msg, "robot_id": robot_id}


@router.post("/loop/confirm/{robot_id}")
def api_confirm_loop(robot_id: int):
    """작업 포인트 확인 — 로봇 태블릿에서 호출하여 다음 구간으로 진행"""
    ok, msg, code = confirm_loop(robot_id)
    if not ok:
        return JSONResponse(status_code=400, content={"detail": msg, "error_code": code, "description": "confirm_loop() — 확인 대기 없음"})
    return {"message": msg, "robot_id": robot_id}


# ─── 태블릿 status 캐시 (빈번 폴링으로 인한 로봇 WS 부하 방지) ──
import time as _time_mod
_tablet_status_cache: dict[int, dict] = {}   # {robot_id: {battery, paused, ts}}
_TABLET_CACHE_TTL = 5.0                      # 5초 캐시


@router.get("/loop/status/{robot_id}")
def api_loop_status(robot_id: int, db: Session = Depends(get_db)):
    """무한반복 작업 상태 조회 (idle일 때 실제 충전 상태 반영)"""
    status = get_loop_status(robot_id)

    robot = db.query(Robot).filter(Robot.id == robot_id, Robot.is_active == True).first()
    amr_label = f"AMR{str(robot.wcs_no).zfill(2)}" if robot and robot.wcs_no else f"AMR{str(robot_id).zfill(2)}"

    # 캐시 체크 (배터리/paused/charging은 3초 캐시)
    now_ts = _time_mod.time()
    cached = _tablet_status_cache.get(robot_id)
    if cached and (now_ts - cached["ts"]) < _TABLET_CACHE_TTL:
        battery_pct = cached["battery"]
        paused = cached["paused"]
        if cached.get("charging") and status.get("status") in ("idle", "stopped"):
            status = {"status": "charging", "message": "충전 중"}
    else:
        # 캐시 미스 → 로봇 조회 (배터리 + control_mode + charging 한 번에)
        battery_pct = None
        paused = False
        is_charging = False

        if robot and robot.ip_address:
            # 배터리 + planning/charging 상태 조회
            try:
                ws_data, _ = _collect_ws_topics(
                    robot.ip_address,
                    ["/battery_state", "/planning_state", "/detailed_battery_state"],
                    timeout_sec=2)
                bs = ws_data.get("/battery_state", {})
                if bs and "percentage" in bs:
                    raw = bs["percentage"]
                    battery_pct = round(raw * 100) if raw <= 1.0 else round(raw)
                if status.get("status") in ("idle", "stopped", "charging"):
                    planning = ws_data.get("/planning_state", {})
                    battery = ws_data.get("/detailed_battery_state", {}) or bs
                    runstate = _to_runstate(planning, battery, online=True)
                    if runstate == "CHARGING":
                        is_charging = True
                        status = {"status": "charging", "message": "충전 중"}
                    elif status.get("status") == "charging":
                        # 메모리는 "충전 중"이지만 실제로는 아님 — 사람이 충전기 뺌
                        status = {"status": "standby", "message": "대기 중"}
                        # 백엔드 메모리도 동기화 (다음 조회에서도 일관)
                        try:
                            from app.robot_api.robot_task_service import _run_info, _task_lock
                            with _task_lock:
                                _run_info[robot_id] = status
                        except Exception:
                            pass
            except Exception:
                pass

            # control_mode (HTTP)
            try:
                import requests as _req
                _r = _req.get(f"http://{robot.ip_address}:8090/chassis/status",
                              headers={"Authorization": "Secret 19a11878aaab420fba94577ce3620dce"},
                              timeout=1)
                if _r.status_code == 200:
                    paused = _r.json().get("control_mode") == "manual"
            except Exception:
                pass

        _tablet_status_cache[robot_id] = {
            "battery": battery_pct,
            "paused": paused,
            "charging": is_charging,
            "ts": now_ts,
        }

    return {"robot_id": robot_id, "amr_label": amr_label, "battery": battery_pct, "paused": paused, **status}


class ChargeRequest(BaseModel):
    route_poi_names: list[str] = Field(default=[], description="충전소까지 경유할 POI 이름 목록 (비어있으면 DB에서 자동 탐색)")


def _find_charge_route(db: Session, robot_id: int) -> list[str]:
    """로봇 충전소까지의 경유 경로를 DB MapLine 그래프에서 자동 탐색"""
    robot = db.query(Robot).filter(Robot.id == robot_id).first()
    if not robot or not robot.charging_id:
        return []

    charging_poi = db.query(MapPOI).filter(
        MapPOI.id == robot.charging_id, MapPOI.is_active == True
    ).first()
    if not charging_poi:
        return []

    # 같은 맵의 WORK 노드 중 가장 가까운 것 → 충전소까지 경로 탐색
    work_pois = db.query(MapPOI).filter(
        MapPOI.map_id == charging_poi.map_id,
        MapPOI.name.like("WORK%"),
        MapPOI.is_active == True,
    ).all()

    if not work_pois:
        return []

    # 각 WORK 노드에서 충전소까지 경로 탐색, 가장 짧은 것 선택
    best_route = None
    for wp in work_pois:
        route = find_route(db, charging_poi.map_id, wp.id, charging_poi.id,
                           include_endpoints=False)
        if route is not None and (best_route is None or len(route) < len(best_route)):
            best_route = route

    return best_route or []


@router.post("/charge/{robot_id}")
def api_charge(robot_id: int, req: ChargeRequest = None, db: Session = Depends(get_db)):
    """로봇을 충전소로 이동 (경유 경로 미지정 시 DB에서 자동 탐색)"""
    ip = _get_robot_ip(db, robot_id)
    if isinstance(ip, JSONResponse):
        return ip

    route_names = []
    if req and req.route_poi_names:
        route_names = req.route_poi_names
    else:
        route_names = _find_charge_route(db, robot_id)

    # 충전소 이름 조회 (charger_name으로 로봇 맵 overlay ID 자동 매칭)
    charger_name = None
    robot = db.query(Robot).filter(Robot.id == robot_id).first()
    if robot and robot.charging_id:
        cpoi = db.query(MapPOI).filter(MapPOI.id == robot.charging_id, MapPOI.is_active == True).first()
        if cpoi:
            charger_name = cpoi.name

    if route_names:
        ok, msg = start_charge_route(robot_id, ip, route_names, charger_name=charger_name)
    else:
        ok, msg = send_charge(ip, charger_name=charger_name)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    _rname = robot.name if robot else f"로봇 {robot_id}"
    log_activity("robot", "robot_charge",
                 f"로봇 '{_rname}' 충전소 이동 요청",
                 robot_id=robot_id, robot_name=_rname, source="api_charge")
    return {"message": msg, "robot_id": robot_id, "route": route_names}


@router.post("/return/{robot_id}")
def api_return(robot_id: int, db: Session = Depends(get_db)):
    """로봇 복귀 — standby_id가 있으면 대기장소, 없으면 충전소로 이동"""
    ip = _get_robot_ip(db, robot_id)
    if isinstance(ip, JSONResponse):
        return ip

    robot = db.query(Robot).filter(Robot.id == robot_id).first()
    if not robot:
        raise HTTPException(status_code=404, detail="로봇을 찾지 못했습니다.")

    dest_poi = None
    dest_type = None

    # 1) standby_id 우선
    if robot.standby_id:
        poi = db.query(MapPOI).filter(
            MapPOI.id == robot.standby_id, MapPOI.is_active == True
        ).first()
        if poi:
            dest_poi = poi
            dest_type = "standby"

    # 2) standby 없으면 charging_id
    if not dest_poi and robot.charging_id:
        poi = db.query(MapPOI).filter(
            MapPOI.id == robot.charging_id, MapPOI.is_active == True
        ).first()
        if poi:
            dest_poi = poi
            dest_type = "charging"

    if not dest_poi:
        raise HTTPException(status_code=400, detail="대기장소/충전소가 설정되지 않았습니다.")

    # ── 다른 로봇이 같은 위치를 점유 중이면 빈 위치 재배정 ──
    other_robots = db.query(Robot).filter(
        Robot.is_active == True, Robot.id != robot_id
    ).all()
    occupied_poi_ids = set()
    for r in other_robots:
        if r.charging_id:
            occupied_poi_ids.add(r.charging_id)
        if r.standby_id:
            occupied_poi_ids.add(r.standby_id)

    if dest_poi.id in occupied_poi_ids:
        # 현재 배정된 위치가 중복 → 빈 위치 탐색
        _POS_ORDER = ["C1", "C2", "C3", "W1", "W2"]
        occupied_names = set()
        for pid in occupied_poi_ids:
            op = db.query(MapPOI).filter(MapPOI.id == pid).first()
            if op:
                occupied_names.add(op.name)

        new_dest = None
        for pos_name in _POS_ORDER:
            if pos_name in occupied_names:
                continue
            candidate = db.query(MapPOI).filter(
                MapPOI.name == pos_name, MapPOI.is_active == True,
                MapPOI.map_id == dest_poi.map_id,
            ).first()
            if candidate:
                new_dest = candidate
                break

        if new_dest:
            dest_poi = new_dest
            dest_type = "standby" if new_dest.name.startswith("W") else "charging"
            # DB 업데이트
            if dest_type == "standby":
                robot.standby_id = new_dest.id
                robot.charging_id = None
            else:
                robot.charging_id = new_dest.id
                robot.standby_id = None
            db.commit()

    # 경유 경로 자동 탐색
    route_names = _find_return_route(db, dest_poi)

    # 목적지 POI를 경로 마지막에 포함
    if route_names:
        route_names.append(dest_poi.name)
    else:
        route_names = [dest_poi.name]

    charger_name = dest_poi.name if dest_type == "charging" else None
    ok, msg = start_return_route(robot_id, ip, route_names, dest_poi.name, charger_name=charger_name)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)

    return {
        "message": msg,
        "robot_id": robot_id,
        "dest_type": dest_type,
        "dest_name": dest_poi.name,
        "route": route_names,
    }


def _find_return_route(db: Session, dest_poi: MapPOI) -> list[str]:
    """현재 로봇 위치(가장 가까운 WORK 노드)에서 목적지까지 경유 경로 탐색"""
    work_pois = db.query(MapPOI).filter(
        MapPOI.map_id == dest_poi.map_id,
        MapPOI.name.like("WORK%"),
        MapPOI.is_active == True,
    ).all()

    if not work_pois:
        return []

    best_route = None
    for wp in work_pois:
        route = find_route(db, dest_poi.map_id, wp.id, dest_poi.id,
                           include_endpoints=False)
        if route is not None and (best_route is None or len(route) < len(best_route)):
            best_route = route

    return best_route or []


@router.post("/stop/{robot_id}")
def api_stop_robot(robot_id: int, db: Session = Depends(get_db)):
    """로봇 현재 이동 명령 즉시 취소 (루프 작업 포함)"""
    ip = _get_robot_ip(db, robot_id)
    if isinstance(ip, JSONResponse):
        return ip

    # 루프 작업이 실행 중이면 루프도 정지
    stop_loop(robot_id, ip)

    # 현재 이동 취소
    ok = cancel_current_move(ip)
    if not ok:
        raise HTTPException(status_code=400, detail="이동 취소 실패")
    robot = db.query(Robot).filter(Robot.id == robot_id).first()
    _rname = robot.name if robot else f"로봇 {robot_id}"
    log_activity("robot", "robot_stop",
                 f"로봇 '{_rname}' 이동 즉시 취소",
                 robot_id=robot_id, robot_name=_rname, source="api_stop_robot")
    return {"message": "이동이 취소되었습니다", "robot_id": robot_id}


@router.post("/robot/{robot_id}/shutdown")
def api_shutdown_robot(robot_id: int, db: Session = Depends(get_db)):
    """로봇 전체 전원 종료"""
    robot = db.query(Robot).filter(Robot.id == robot_id, Robot.is_active == True).first()
    if not robot or not robot.ip_address:
        raise HTTPException(status_code=404, detail="로봇을 찾을 수 없습니다")
    ip = robot.ip_address
    secret = "19a11878aaab420fba94577ce3620dce"
    try:
        import requests as http_req
        r = http_req.post(
            f"http://{ip}:8090/services/baseboard/shutdown",
            headers={"Authorization": f"Secret {secret}", "Content-Type": "application/json"},
            json={"target": "main_power_supply", "reboot": False},
            timeout=10,
        )
        r.raise_for_status()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"로봇 종료 실패: {e}")
    _rname = robot.name if robot else f"로봇 {robot_id}"
    log_activity("robot", "robot_shutdown",
                 f"로봇 '{_rname}' 전원 종료",
                 robot_id=robot_id, robot_name=_rname, source="api_shutdown_robot")
    return {"message": "로봇 종료 명령 전송 완료", "robot_id": robot_id}


# ─── 로봇 태블릿용 확인 페이지 ──────────────────────────────────────────────────

@router.get("/tablet/demo", response_class=HTMLResponse)
def tablet_demo_page_route():
    """태블릿 화면 전체 상태 미리보기 (데모) — /tablet/{robot_id} 보다 먼저 등록"""
    return tablet_demo_page()

@router.get("/tablet/{robot_id}", response_class=HTMLResponse)
def tablet_page(robot_id: int, db: Session = Depends(get_db)):
    """로봇 태블릿 브라우저에서 열 확인 페이지"""
    robot = db.query(Robot).filter(Robot.id == robot_id).first()
    amr_label = f"AMR{str(robot.wcs_no).zfill(2)}" if robot and robot.wcs_no else f"AMR{str(robot_id).zfill(2)}"
    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,user-scalable=no">
<title>로봇 {robot_id} 작업 확인</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family:'Noto Sans KR',sans-serif; background:#1a1a2e; color:#fff;
        display:flex; flex-direction:column; align-items:center; justify-content:center;
        height:100vh; overflow:hidden; }}
.status-box {{ text-align:center; width:90%; max-width:900px;
               display:flex; flex-direction:column; align-items:center; gap:1.5vh; }}
.battery-label {{ position:fixed; left:16px; top:50%; transform:translateY(-50%);
                  display:flex; flex-direction:column; align-items:center; gap:8px;
                  font-size:clamp(1.2rem,3vw,1.6rem); font-weight:700; color:#aaa; z-index:1001; }}
.battery-icon {{ display:block; width:clamp(44px,8vw,64px); height:clamp(22px,4vw,32px);
                 border:3px solid #aaa; border-radius:4px; position:relative; }}
.battery-icon::after {{ content:''; position:absolute; right:-7px; top:20%; width:4px; height:60%;
                        background:#aaa; border-radius:0 3px 3px 0; }}
.battery-fill {{ height:100%; border-radius:1px; transition:width 0.5s; }}
.amr-label {{ font-size:2.5rem; font-size:clamp(2rem,6vw,4rem); font-weight:800; color:#42a5f5;
              letter-spacing:0.05em; }}
.poi-name {{ font-size:clamp(3rem,10vw,7rem); font-weight:800; line-height:1.3;
             color:#e94560; word-break:keep-all; white-space:pre-line; }}
.status-text {{ font-size:clamp(1.6rem,5vw,3rem); line-height:1.4; color:#aaa;
                word-break:keep-all; }}
.loop-info {{ font-size:clamp(1.2rem,3.5vw,2rem); line-height:1.3; color:#666; }}

#btn-confirm {{
  display:none; width:80vw; max-width:560px; height:clamp(80px,18vh,160px);
  font-size:clamp(2rem,6vw,3.5rem); font-weight:800; border:none; border-radius:24px;
  background:linear-gradient(135deg,#e94560,#c23152); color:#fff;
  cursor:pointer; box-shadow:0 12px 40px rgba(233,69,96,0.5);
  transition:transform .1s,box-shadow .1s;
  justify-content:center; align-items:center;
  margin-top:1vh;
}}
#btn-confirm:active {{
  transform:scale(0.95);
  box-shadow:0 6px 20px rgba(233,69,96,0.3);
}}
#btn-confirm.show {{ display:flex; }}

.running {{ color:#0be881; }}
.waiting {{ color:#ffc048; }}
.error {{ color:#e94560; }}
.idle {{ color:#666; }}
.charging {{ color:#00d2d3; }}
.moving {{ color:#a29bfe; }}

.spinner {{
  display:inline-block; width:clamp(20px,4vw,36px); height:clamp(20px,4vw,36px);
  border:4px solid rgba(255,255,255,0.2); border-top-color:#fff;
  border-radius:50%; animation:spin 0.8s linear infinite; margin-right:10px;
  vertical-align:middle;
}}
@keyframes spin {{ to {{ transform:rotate(360deg); }} }}

.stuck-banner {{
  display:none; position:fixed; top:0; left:0; right:0;
  background:linear-gradient(135deg,#e94560,#c23152); color:#fff;
  text-align:center; font-size:clamp(1.6rem,5vw,2.8rem); font-weight:800;
  padding:clamp(12px,3vh,28px) 20px; z-index:1000;
  animation:pulse 1.5s ease-in-out infinite;
}}
.stuck-banner.show {{ display:block; }}
@keyframes pulse {{
  0%,100% {{ opacity:1; }}
  50% {{ opacity:0.6; }}
}}
#btn-shutdown {{
  position:fixed; bottom:16px; right:16px;
  width:clamp(48px,8vw,64px); height:clamp(48px,8vw,64px);
  font-size:clamp(0.7rem,2vw,1rem); font-weight:800;
  background:rgba(233,69,96,0.15); border:2px solid rgba(233,69,96,0.4);
  border-radius:50%; color:rgba(233,69,96,0.6);
  cursor:pointer; z-index:1002;
  display:flex; align-items:center; justify-content:center;
}}
#btn-shutdown:active {{ background:rgba(233,69,96,0.4); color:#fff; }}
.shutdown-confirm {{
  display:none; position:fixed; inset:0; background:rgba(0,0,0,0.85);
  z-index:2000; flex-direction:column; align-items:center; justify-content:center; gap:2vh;
}}
.shutdown-confirm.show {{ display:flex; }}
.shutdown-confirm .msg {{ font-size:clamp(1.8rem,5vw,3rem); font-weight:700; color:#e94560; }}
.shutdown-confirm .sub {{ font-size:clamp(1rem,3vw,1.6rem); color:#aaa; }}
.shutdown-confirm .btns {{ display:flex; gap:20px; margin-top:2vh; }}
.shutdown-confirm .btns button {{
  width:clamp(140px,30vw,200px); height:clamp(60px,12vh,100px);
  font-size:clamp(1.2rem,3.5vw,2rem); font-weight:700; border:none; border-radius:16px;
  cursor:pointer;
}}
.shutdown-confirm .btn-yes {{ background:#e94560; color:#fff; }}
.shutdown-confirm .btn-no {{ background:#333; color:#aaa; border:1px solid #555; }}
</style>
</head>
<body>

<div class="stuck-banner" id="stuckBanner">장애물 감지 — 작업중입니다. 비켜주세요!</div>
<button id="btn-shutdown" onclick="showShutdown()">OFF</button>
<div class="shutdown-confirm" id="shutdownConfirm">
  <div class="msg">로봇 전원을 종료하시겠습니까?</div>
  <div class="sub">종료 후 수동으로만 다시 켤 수 있습니다</div>
  <div class="btns">
    <button class="btn-yes" onclick="doShutdown()">종료</button>
    <button class="btn-no" onclick="hideShutdown()">취소</button>
  </div>
</div>

<div class="battery-label">
  <div class="battery-icon"><div class="battery-fill" id="batteryFill" style="width:0%;background:#aaa;"></div></div>
  <span id="batteryText">--%</span>
</div>

<div class="status-box">
  <div class="amr-label">{amr_label}</div>
  <div class="poi-name" id="poiName">-</div>
  <div class="status-text" id="statusText">연결 중...</div>
  <div class="loop-info" id="loopInfo"></div>
  <button id="btn-confirm" onclick="doConfirm()">✔ 작업 확인</button>
</div>

<script>
const ROBOT_ID = {robot_id};
const API = window.location.origin + '/api/tasks';
const AUDIO_URL = window.location.origin + '/static/audio/please_move.mp3';
let polling = null;
let stuckAudio = null;
let wasStuck = false;
let audioPlaying = false;
let autoConfirmTimer = null;
const AUTO_CONFIRM_SEC = 5;

// 종료 기능
function showShutdown() {{ document.getElementById('shutdownConfirm').classList.add('show'); }}
function hideShutdown() {{ document.getElementById('shutdownConfirm').classList.remove('show'); }}
async function doShutdown() {{
  try {{
    const r = await fetch(API + '/robot/' + ROBOT_ID + '/shutdown', {{ method: 'POST' }});
    if (r.ok) {{
      document.querySelector('.shutdown-confirm .msg').textContent = '종료 명령 전송 완료';
      document.querySelector('.shutdown-confirm .sub').textContent = '잠시 후 로봇이 종료됩니다';
      document.querySelector('.shutdown-confirm .btns').style.display = 'none';
    }} else {{
      const d = await r.json();
      document.querySelector('.shutdown-confirm .sub').textContent = d.detail || '종료 실패';
    }}
  }} catch(e) {{
    document.querySelector('.shutdown-confirm .sub').textContent = '서버 연결 실패';
  }}
}}

// 음성 재생 (장애물 감지 시)
function playStuckAudio() {{
  if (audioPlaying) return;
  if (!stuckAudio) {{
    stuckAudio = new Audio(AUDIO_URL);
    stuckAudio.addEventListener('ended', () => {{ audioPlaying = false; }});
    stuckAudio.addEventListener('error', () => {{ audioPlaying = false; }});
  }}
  audioPlaying = true;
  stuckAudio.currentTime = 0;
  stuckAudio.play().catch(() => {{ audioPlaying = false; }});
}}

function handleStuck(isStuck) {{
  const banner = document.getElementById('stuckBanner');
  if (isStuck) {{
    banner.classList.add('show');
  }} else {{
    banner.classList.remove('show');
  }}
  wasStuck = isStuck;
}}

// POI 이름 → 표시명 매핑
const poiDisplayName = {{
  'WORK2': '피킹',
  'WORK4': '투입',
}};

async function fetchStatus() {{
  try {{
    const r = await fetch(API + '/loop/status/' + ROBOT_ID);
    const d = await r.json();
    render(d);
  }} catch(e) {{
    document.getElementById('statusText').innerHTML =
      '<span class="error">서버 연결 실패</span>';
  }}
}}

function render(d) {{
  handleStuck(!!d.stuck);
  // 배터리 표시
  if (d.battery != null) {{
    const pct = Math.round(d.battery);
    document.getElementById('batteryText').textContent = pct + '%';
    const fill = document.getElementById('batteryFill');
    fill.style.width = pct + '%';
    fill.style.background = pct <= 20 ? '#e94560' : pct <= 50 ? '#ffc048' : '#0be881';
    document.querySelector('.battery-icon').style.borderColor = pct <= 20 ? '#e94560' : '#aaa';
    document.querySelector('.battery-label span').style.color = pct <= 20 ? '#e94560' : '#aaa';
  }}
  // 일시정지 표시
  if (d.paused) {{
    document.getElementById('poiName').textContent = '일시정지';
    document.getElementById('poiName').style.color = '#ff6b6b';
    document.getElementById('statusText').style.display = '';
    document.getElementById('statusText').innerHTML = '<span style="color:#ff9999">다시 출발 대기 중</span>';
    document.getElementById('btn-confirm').classList.remove('show');
    return;
  }}
  const poi = d.current_poi || '';
  const btn = document.getElementById('btn-confirm');
  const poiEl = document.getElementById('poiName');
  const statusEl = document.getElementById('statusText');
  const loopEl = document.getElementById('loopInfo');
  const stopName = poiDisplayName[poi];

  statusEl.style.display = 'none';
  cancelAutoConfirm();
  btn.classList.remove('show');

  if (d.status === 'moving_to_start' || d.status === 'starting') {{
    poiEl.textContent = '피킹 장소로\\n이동 중';
    poiEl.style.color = '#a29bfe';
    statusEl.style.display = '';
    statusEl.innerHTML = '<span class="moving"><span class="spinner"></span></span>';
    if (d.show_confirm && !confirmCooldown) {{ btn.classList.add('show'); }}
  }} else if (d.status === 'resuming') {{
    poiEl.textContent = '작업 위치로\\n이동 중';
    poiEl.style.color = '#a29bfe';
    statusEl.style.display = '';
    statusEl.innerHTML = '<span class="moving"><span class="spinner"></span></span>';
  }} else if (d.status === 'running') {{
    const msg = d.message || '';
    if (msg.includes('피킹')) {{
      poiEl.textContent = '피킹 장소로\\n이동 중';
    }} else if (msg.includes('투입')) {{
      poiEl.textContent = '투입 장소로\\n이동 중';
    }} else {{
      poiEl.textContent = '이동 중';
    }}
    poiEl.style.color = '#0be881';
    statusEl.style.display = '';
    statusEl.innerHTML = '<span class="running"><span class="spinner"></span></span>';
    if (d.show_confirm && !confirmCooldown) {{ btn.classList.add('show'); }}
  }} else if (d.status === 'waiting_confirmation') {{
    const msg = d.message || '';
    if (msg.includes('피킹')) {{
      poiEl.textContent = '피킹 장소\\n대기';
    }} else if (msg.includes('투입')) {{
      poiEl.textContent = '투입 장소\\n대기';
    }} else {{
      poiEl.textContent = stopName || poi;
    }}
    poiEl.style.color = '#ffc048';
    if (!confirmCooldown) {{ btn.classList.add('show'); }}
  }} else if (d.status === 'evacuating') {{
    poiEl.textContent = '대피 장소로\\n이동 중';
    poiEl.style.color = '#e94560';
    statusEl.style.display = '';
    statusEl.innerHTML = '<span class="error"><span class="spinner"></span></span>';
  }} else if (d.status === 'returning' || d.status === 'finishing') {{
    poiEl.textContent = '복귀 장소로\\n이동 중';
    poiEl.style.color = '#a29bfe';
    statusEl.style.display = '';
    statusEl.innerHTML = '<span class="moving"><span class="spinner"></span></span>';
  }} else if (d.status === 'charging_route' || d.status === 'low_battery_charging') {{
    poiEl.textContent = '복귀 장소로\\n이동 중';
    poiEl.style.color = '#00d2d3';
    statusEl.style.display = '';
    statusEl.innerHTML = '<span class="charging"><span class="spinner"></span></span>';
  }} else if (d.status === 'charging') {{
    poiEl.textContent = '충전 중';
    poiEl.style.color = '#00d2d3';
  }} else if (d.status === 'standby') {{
    poiEl.textContent = '대기 중';
    poiEl.style.color = '#666';
  }} else if (d.status === 'error') {{
    poiEl.textContent = '오류 발생';
    poiEl.style.color = '#e94560';
    if (d.message) {{
      statusEl.style.display = '';
      statusEl.innerHTML = '<span class="error">' + d.message + '</span>';
    }}
  }} else {{
    poiEl.textContent = '대기 중';
    poiEl.style.color = '#666';
  }}

  loopEl.textContent = d.loop ? ('반복 ' + d.loop + '회') : '';
}}

function startAutoConfirm() {{
  if (autoConfirmTimer) return;
  autoConfirmTimer = setTimeout(() => {{
    autoConfirmTimer = null;
    doConfirm();
  }}, AUTO_CONFIRM_SEC * 1000);
}}

function cancelAutoConfirm() {{
  if (autoConfirmTimer) {{
    clearTimeout(autoConfirmTimer);
    autoConfirmTimer = null;
  }}
}}

let confirmCooldown = false;
async function doConfirm() {{
  if (confirmCooldown) return;
  cancelAutoConfirm();
  const btn = document.getElementById('btn-confirm');
  btn.disabled = true;
  confirmCooldown = true;
  try {{
    const r = await fetch(API + '/loop/confirm/' + ROBOT_ID, {{ method: 'POST' }});
    const d = await r.json();
    if (r.ok) {{
      btn.classList.remove('show');
      btn.textContent = '✔ 작업 확인';
      btn.style.background = '';
      // 3초 쿨다운 — 다음 버튼 표시 방지
      setTimeout(() => {{ confirmCooldown = false; btn.disabled = false; }}, 3000);
    }} else {{
      btn.textContent = d.detail || '오류';
      setTimeout(() => {{ confirmCooldown = false; btn.disabled = false; btn.textContent = '✔ 작업 확인'; }}, 1000);
    }}
  }} catch(e) {{
    btn.textContent = '전송 실패';
    setTimeout(() => {{ confirmCooldown = false; btn.disabled = false; btn.textContent = '✔ 작업 확인'; }}, 1000);
  }}
}}

// 폴링
fetchStatus();
polling = setInterval(fetchStatus, 1000);
</script>
</body>
</html>"""
    return Response(html, media_type="text/html", headers={
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache",
        "Expires": "0",
    })


def tablet_demo_page():
    """태블릿 화면 전체 상태 미리보기 (데모) — 구현부"""
    statuses = [
        {"status": "idle", "label": "대기 중"},
        {"status": "moving_to_start", "label": "피킹 장소로 이동 중"},
        {"status": "waiting_confirmation", "label": "피킹 대기", "message": "피킹 장소 대기", "current_poi": "WORK2"},
        {"status": "waiting_confirmation", "label": "투입 대기", "message": "투입 장소 대기", "current_poi": "WORK4"},
        {"status": "evacuating", "label": "대피 이동 중"},
        {"status": "returning", "label": "복귀 장소로 이동 중"},
        {"status": "charging_route", "label": "충전소로 이동 중"},
        {"status": "charging", "label": "충전 중"},
        {"status": "standby", "label": "대기 중"},
        {"status": "error", "label": "오류 발생", "message": "네비게이션 실패"},
        {"status": "running", "label": "장애물 감지 (이동 중)", "message": "피킹 장소로 이동 중", "stuck": True},
    ]
    import json as _j
    cards_html = ""
    for i, s in enumerate(statuses):
        cards_html += f"""
        <div class="demo-card" onclick="showPreview({i})">
          <div class="demo-label">{s['label']}</div>
        </div>"""

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>태블릿 데모</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family:'Noto Sans KR',sans-serif; background:#0f0f23; color:#fff; padding:20px; }}
h1 {{ text-align:center; margin-bottom:20px; font-size:1.5rem; color:#42a5f5; }}
.demo-grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(280px,1fr)); gap:12px; }}
.demo-card {{
  background:#1a1a2e; border:1px solid #333; border-radius:12px;
  padding:16px; cursor:pointer; transition:border-color 0.2s;
}}
.demo-card:hover {{ border-color:#42a5f5; }}
.demo-label {{ font-size:1.1rem; font-weight:700; margin-bottom:4px; }}
.demo-status {{ font-size:0.85rem; color:#666; font-family:monospace; }}
.preview-overlay {{
  display:none; position:fixed; inset:0; background:rgba(0,0,0,0.9);
  z-index:3000; flex-direction:column; align-items:center; justify-content:center;
}}
.preview-overlay.show {{ display:flex; }}
.preview-frame {{
  width:min(90vw, 960px); aspect-ratio:16/10;
  background:#1a1a2e; border-radius:16px; overflow:hidden;
  display:flex; flex-direction:column; align-items:center; justify-content:center;
  position:relative; gap:1.5vh; padding:20px;
}}
.preview-close {{
  position:absolute; top:12px; right:16px; font-size:2rem;
  color:#aaa; cursor:pointer; background:none; border:none; z-index:1;
}}
.preview-close:hover {{ color:#fff; }}
.preview-title {{ color:#42a5f5; font-size:1rem; margin-top:10px; }}

/* 태블릿 스타일 복제 */
.p-frame {{
  width:min(90vw, 960px); aspect-ratio:16/10;
  background:#1a1a2e; border-radius:16px; overflow:hidden;
  display:flex; flex-direction:column; align-items:center; justify-content:center;
  position:relative; gap:1.5vh; padding:20px;
}}
.p-battery {{ position:absolute; left:16px; top:50%; transform:translateY(-50%);
  display:flex; flex-direction:column; align-items:center; gap:8px;
  font-size:1.1rem; font-weight:700; color:#aaa; }}
.p-battery-icon {{ display:block; width:48px; height:24px; border:3px solid #aaa; border-radius:4px; position:relative; }}
.p-battery-icon::after {{ content:''; position:absolute; right:-6px; top:20%; width:4px; height:60%; background:#aaa; border-radius:0 3px 3px 0; }}
.p-battery-fill {{ height:100%; border-radius:1px; width:72%; background:#0be881; }}
.p-amr {{ font-size:2.5rem; font-weight:800; color:#42a5f5; }}
.p-poi {{ font-size:4rem; font-weight:800; line-height:1.3; white-space:pre-line; text-align:center; }}
.p-status {{ font-size:1.5rem; color:#aaa; }}
.p-btn {{
  display:none; width:60%; max-width:400px; height:70px;
  font-size:1.8rem; font-weight:800; border:none; border-radius:16px;
  background:linear-gradient(135deg,#e94560,#c23152); color:#fff;
  cursor:default; justify-content:center; align-items:center;
  box-shadow:0 8px 30px rgba(233,69,96,0.4);
}}
.p-btn.show {{ display:flex; }}
.p-shutdown {{ position:absolute; bottom:12px; right:12px; width:44px; height:44px;
  font-size:0.7rem; font-weight:800; background:rgba(233,69,96,0.15); border:2px solid rgba(233,69,96,0.4);
  border-radius:50%; color:rgba(233,69,96,0.6); display:flex; align-items:center;
  justify-content:center; cursor:default; }}
.p-stuck {{ display:none; position:absolute; top:0; left:0; right:0;
  background:linear-gradient(135deg,#e94560,#c23152); color:#fff;
  text-align:center; font-size:1.2rem; font-weight:800; padding:8px;
  border-radius:16px 16px 0 0; }}
.p-stuck.show {{ display:block; }}
.spinner {{
  display:inline-block; width:24px; height:24px;
  border:3px solid rgba(255,255,255,0.2); border-top-color:#fff;
  border-radius:50%; animation:spin 0.8s linear infinite;
  margin-right:8px; vertical-align:middle;
}}
@keyframes spin {{ to {{ transform:rotate(360deg); }} }}
</style>
</head>
<body>
<h1>태블릿 화면 미리보기 (총 {len(statuses)}개 상태)</h1>
<div class="demo-grid">{cards_html}</div>

<div class="preview-overlay" id="previewOverlay" onclick="closePreview(event)">
  <div class="p-frame" onclick="event.stopPropagation()">
    <button class="preview-close" onclick="closePreview()">&times;</button>
    <div class="p-stuck" id="pStuck">장애물 감지 — 작업중입니다. 비켜주세요!</div>
    <div class="p-battery">
      <div class="p-battery-icon"><div class="p-battery-fill"></div></div>
      <span>72%</span>
    </div>
    <div class="p-amr">AMR01</div>
    <div class="p-poi" id="pPoi">-</div>
    <div class="p-status" id="pStatus"></div>
    <div class="p-btn" id="pBtn">✔ 작업 확인</div>
    <div class="p-shutdown">OFF</div>
    <div class="preview-title" id="pTitle"></div>
  </div>
</div>

<script>
const STATUSES = {_j.dumps(statuses, ensure_ascii=False)};
const poiDisplayName = {{ 'WORK2': '투입', 'WORK4': '배출' }};

function showPreview(i) {{
  const s = STATUSES[i];
  const poi = s.current_poi || '';
  const msg = s.message || '';
  const stopName = poiDisplayName[poi];
  const poiEl = document.getElementById('pPoi');
  const statusEl = document.getElementById('pStatus');
  const btnEl = document.getElementById('pBtn');
  const titleEl = document.getElementById('pTitle');

  statusEl.style.display = 'none';
  statusEl.innerHTML = '';
  btnEl.classList.remove('show');
  titleEl.textContent = s.label;
  const stuckEl = document.getElementById('pStuck');
  if (s.stuck) {{ stuckEl.classList.add('show'); }} else {{ stuckEl.classList.remove('show'); }}

  if (s.status === 'moving_to_start' || s.status === 'starting') {{
    poiEl.textContent = '피킹 장소로\\n이동 중'; poiEl.style.color = '#a29bfe';
    statusEl.style.display = ''; statusEl.innerHTML = '<span class="spinner"></span>';
  }} else if (s.status === 'resuming') {{
    poiEl.textContent = '작업 위치로\\n이동 중'; poiEl.style.color = '#a29bfe';
    statusEl.style.display = ''; statusEl.innerHTML = '<span class="spinner"></span>';
  }} else if (s.status === 'running') {{
    if (msg.includes('피킹')) poiEl.textContent = '피킹 장소로\\n이동 중';
    else if (msg.includes('투입')) poiEl.textContent = '투입 장소로\\n이동 중';
    else poiEl.textContent = '이동 중';
    poiEl.style.color = '#0be881';
    statusEl.style.display = ''; statusEl.innerHTML = '<span class="spinner"></span>';
  }} else if (s.status === 'waiting_confirmation') {{
    if (msg.includes('피킹')) poiEl.textContent = '피킹 장소\\n대기';
    else if (msg.includes('투입')) poiEl.textContent = '투입 장소\\n대기';
    else poiEl.textContent = stopName || poi;
    poiEl.style.color = '#ffc048';
    btnEl.classList.add('show');
  }} else if (s.status === 'evacuating') {{
    poiEl.textContent = '대피 장소로\\n이동 중'; poiEl.style.color = '#e94560';
    statusEl.style.display = ''; statusEl.innerHTML = '<span class="spinner"></span>';
  }} else if (s.status === 'returning' || s.status === 'finishing') {{
    poiEl.textContent = '복귀 장소로\\n이동 중'; poiEl.style.color = '#a29bfe';
    statusEl.style.display = ''; statusEl.innerHTML = '<span class="spinner"></span>';
  }} else if (s.status === 'charging_route' || s.status === 'low_battery_charging') {{
    poiEl.textContent = '복귀 장소로\\n이동 중'; poiEl.style.color = '#00d2d3';
    statusEl.style.display = ''; statusEl.innerHTML = '<span class="spinner"></span>';
  }} else if (s.status === 'charging') {{
    poiEl.textContent = '충전 중'; poiEl.style.color = '#00d2d3';
  }} else if (s.status === 'standby') {{
    poiEl.textContent = '대기 중'; poiEl.style.color = '#666';
  }} else if (s.status === 'error') {{
    poiEl.textContent = '오류 발생'; poiEl.style.color = '#e94560';
    if (msg) {{ statusEl.style.display = ''; statusEl.innerHTML = '<span style="color:#e94560">' + msg + '</span>'; }}
  }} else {{
    poiEl.textContent = '대기 중'; poiEl.style.color = '#666';
  }}

  document.getElementById('previewOverlay').classList.add('show');
}}

function closePreview(e) {{
  if (e && e.target !== document.getElementById('previewOverlay')) return;
  document.getElementById('previewOverlay').classList.remove('show');
}}
</script>
</body>
</html>"""
    return Response(html, media_type="text/html")
