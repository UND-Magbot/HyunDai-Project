from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.robot import Robot
from app.robot_api.robot_task_service import start_loop, stop_loop, get_loop_status, confirm_loop, send_charge, start_charge_route
from app.robot_api.robot_live_service import _collect_ws_topics, _to_runstate

router = APIRouter(prefix="/api/tasks", tags=["작업 관리"])


# ─── 요청 스키마 ───────────────────────────────────────────────────────────────

class LoopStartRequest(BaseModel):
    robot_id: int
    poi_names: list[str] = Field(..., min_length=1, description="순서대로 방문할 POI 이름 목록")
    stop_names: list[str] = Field(default=[], description="작업 포인트 (정지할 POI 이름). 비어있으면 모든 POI에서 정지")
    entry_poi_names: list[str] = Field(default=[], description="진입 경로 POI (충전소→작업구역, 최초 1회만 통과)")


# ─── 헬퍼 ─────────────────────────────────────────────────────────────────────

def _get_robot_ip(db: Session, robot_id: int) -> str:
    robot = db.query(Robot).filter(Robot.id == robot_id, Robot.is_active == True).first()
    if not robot:
        raise HTTPException(status_code=404, detail="로봇을 찾을 수 없습니다")
    if not robot.ip_address:
        raise HTTPException(status_code=400, detail="로봇 IP 주소가 등록되지 않았습니다")
    return robot.ip_address


# ─── 엔드포인트 ────────────────────────────────────────────────────────────────

@router.post("/loop/start")
def api_start_loop(req: LoopStartRequest, db: Session = Depends(get_db)):
    """무한반복 작업 시작
    - poi_names: DB map_pois 테이블의 POI name 목록 (순서대로 방문)
    - 예시: ["CUR-001", "CUR-002"]
    """
    ip = _get_robot_ip(db, req.robot_id)

    # is_running 체크는 start_loop 내부에서 처리 (정리 로직 포함)
    ok, msg = start_loop(req.robot_id, ip, req.poi_names, req.stop_names, req.entry_poi_names)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)

    return {"message": msg, "robot_id": req.robot_id, "poi_names": req.poi_names, "stop_names": req.stop_names, "entry_poi_names": req.entry_poi_names}


@router.post("/loop/stop/{robot_id}")
def api_stop_loop(robot_id: int, db: Session = Depends(get_db)):
    """무한반복 작업 정지"""
    ip = _get_robot_ip(db, robot_id)
    ok, msg = stop_loop(robot_id, ip)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)

    return {"message": msg, "robot_id": robot_id}


@router.post("/loop/confirm/{robot_id}")
def api_confirm_loop(robot_id: int):
    """작업 포인트 확인 — 로봇 태블릿에서 호출하여 다음 구간으로 진행"""
    ok, msg = confirm_loop(robot_id)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"message": msg, "robot_id": robot_id}


@router.get("/loop/status/{robot_id}")
def api_loop_status(robot_id: int, db: Session = Depends(get_db)):
    """무한반복 작업 상태 조회 (idle일 때 실제 충전 상태 반영)"""
    status = get_loop_status(robot_id)

    if status.get("status") in ("idle", "stopped"):
        robot = db.query(Robot).filter(Robot.id == robot_id, Robot.is_active == True).first()
        if robot and robot.ip_address:
            try:
                ws_data, _ = _collect_ws_topics(robot.ip_address, ["/planning_state", "/detailed_battery_state", "/battery_state"], timeout_sec=3)
                planning = ws_data.get("/planning_state", {})
                battery = ws_data.get("/detailed_battery_state", {}) or ws_data.get("/battery_state", {})
                runstate = _to_runstate(planning, battery, online=True)
                if runstate == "CHARGING":
                    status = {"status": "charging", "message": "충전 중"}
            except Exception:
                pass

    return {"robot_id": robot_id, **status}


class ChargeRequest(BaseModel):
    route_poi_names: list[str] = Field(default=[], description="충전소까지 경유할 POI 이름 목록 (예: ENTERPOS3→ENTERPOS2→ENTERPOS1)")


@router.post("/charge/{robot_id}")
def api_charge(robot_id: int, req: ChargeRequest = None, db: Session = Depends(get_db)):
    """로봇을 충전소로 이동 (경유 경로 지정 가능)"""
    ip = _get_robot_ip(db, robot_id)
    if req and req.route_poi_names:
        ok, msg = start_charge_route(robot_id, ip, req.route_poi_names)
    else:
        ok, msg = send_charge(ip)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"message": msg, "robot_id": robot_id}


# ─── 로봇 태블릿용 확인 페이지 ──────────────────────────────────────────────────

@router.get("/tablet/{robot_id}", response_class=HTMLResponse)
def tablet_page(robot_id: int):
    """로봇 태블릿 브라우저에서 열 확인 페이지"""
    return f"""<!DOCTYPE html>
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
.poi-name {{ font-size:clamp(3rem,10vw,7rem); font-weight:800; line-height:1.2;
             color:#e94560; word-break:keep-all; }}
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
</style>
</head>
<body>

<div class="stuck-banner" id="stuckBanner">장애물 감지 — 작업중입니다. 비켜주세요!</div>

<div class="status-box">
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
    if (!wasStuck) {{
      playStuckAudio();
    }}
  }} else {{
    banner.classList.remove('show');
  }}
  wasStuck = isStuck;
}}

// POI 이름 → 표시명 매핑
const poiDisplayName = {{
  'CURPOS2': '투입',
  'CURPOS4': '배출',
}};

const statusMap = {{
  'idle': ['대기 중', 'idle'],
  'starting': ['시작 중...', 'running'],
  'running': ['이동 중', 'running'],
  'waiting_confirmation': ['작업 확인 대기', 'waiting'],
  'stopped': ['정지됨', 'idle'],
  'error': ['오류 발생', 'error'],
  'charging_route': ['충전소 이동 중', 'charging'],
  'charging': ['충전 중', 'charging'],
  'low_battery_charging': ['배터리 부족 → 충전소 이동 중', 'charging'],
  'moving_to_start': ['작업 시작 위치로 이동 중', 'moving'],
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
  // 장애물 감지 처리
  handleStuck(!!d.stuck);

  const poi = d.current_poi || '-';
  const [label, cls] = statusMap[d.status] || [d.status, 'idle'];
  const btn = document.getElementById('btn-confirm');
  const poiEl = document.getElementById('poiName');
  const statusEl = document.getElementById('statusText');
  const loopEl = document.getElementById('loopInfo');

  if (d.status === 'idle' || d.status === 'stopped') {{
    poiEl.textContent = label;
    statusEl.style.display = 'none';
    btn.classList.remove('show');
  }} else if (d.status === 'moving_to_start') {{
    poiEl.textContent = label;
    poiEl.style.color = '#a29bfe';
    statusEl.style.display = '';
    statusEl.innerHTML = '<span class="moving"><span class="spinner"></span>' + (d.message || '') + '</span>';
    btn.classList.remove('show');
    loopEl.textContent = '';
    return;
  }} else if (d.status === 'charging_route' || d.status === 'charging' || d.status === 'low_battery_charging') {{
    poiEl.textContent = label;
    poiEl.style.color = '#00d2d3';
    statusEl.style.display = '';
    statusEl.innerHTML = '<span class="charging"><span class="spinner"></span>' + (d.message || '') + '</span>';
    btn.classList.remove('show');
    loopEl.textContent = '';
    return;
  }} else {{
    poiEl.style.color = '#e94560';
    poiEl.textContent = poiDisplayName[poi] || poi;
    statusEl.style.display = '';
    if (d.status === 'waiting_confirmation') {{
      statusEl.innerHTML = '<span class="waiting">' + label + '</span>';
      btn.classList.add('show');
    }} else if (d.status === 'running' || d.status === 'charging_route' || d.status === 'charging') {{
      statusEl.innerHTML = '<span class="' + cls + '"><span class="spinner"></span>' + label + '</span>';
      btn.classList.remove('show');
    }} else {{
      statusEl.innerHTML = '<span class="' + cls + '">' + label + '</span>';
      btn.classList.remove('show');
    }}
  }}

  if (d.status === 'error' && d.message) {{
    statusEl.innerHTML += '<br><span style="color:#999;font-size:0.7em">' + d.message + '</span>';
  }}

  if (d.loop) {{
    let info = '루프 ' + d.loop + '회';
    if (d.current_segment && d.total_segments) {{
      info += ' | 구간 ' + d.current_segment + '/' + d.total_segments;
    }}
    loopEl.textContent = info;
  }} else {{
    loopEl.textContent = '';
  }}
}}

async function doConfirm() {{
  const btn = document.getElementById('btn-confirm');
  btn.disabled = true;
  btn.textContent = '전송 중...';
  try {{
    const r = await fetch(API + '/loop/confirm/' + ROBOT_ID, {{ method: 'POST' }});
    const d = await r.json();
    if (r.ok) {{
      btn.textContent = '✔ 확인 완료';
      btn.style.background = 'linear-gradient(135deg,#0be881,#05c46b)';
      setTimeout(() => {{
        btn.classList.remove('show');
        btn.disabled = false;
        btn.textContent = '✔ 작업 확인';
        btn.style.background = '';
      }}, 1500);
    }} else {{
      btn.textContent = d.detail || '오류';
      setTimeout(() => {{ btn.disabled = false; btn.textContent = '✔ 작업 확인'; }}, 2000);
    }}
  }} catch(e) {{
    btn.textContent = '전송 실패';
    setTimeout(() => {{ btn.disabled = false; btn.textContent = '✔ 작업 확인'; }}, 2000);
  }}
}}

// 2초 간격 폴링
fetchStatus();
polling = setInterval(fetchStatus, 2000);
</script>
</body>
</html>"""
