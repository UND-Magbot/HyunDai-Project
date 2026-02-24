"""
로봇 작업 실행 서비스
- DB map_pois 테이블에서 POI 좌표를 읽어 순차 이동
- AutoXing 로컬 HTTP API (포트 8090) 직접 통신
- WebSocket /planning_state 구독으로 이동 상태 실시간 감시 (HTTP 폴링 제거)
- 무한반복 지원
"""
import json
import time
import threading
import logging
import requests
from websocket import create_connection, WebSocketException

from app.database import SessionLocal
from app.models.map import MapPOI
from app.models.robot import Robot

logger = logging.getLogger(__name__)

PORT = 8090
MOVE_TIMEOUT = 300       # 단일 이동 최대 대기 시간 (초)
WS_RECV_TIMEOUT = 3.0    # WebSocket recv 대기 시간 (초)
WS_SILENCE_LIMIT = 15.0  # WebSocket 무응답 허용 시간 (초) — 초과 시 연결 끊김 판단
RECOVERY_DELAY = 3.0     # cancel 후 새 이동 전 물리적 복구 대기 (초)

# 스레드 안전한 공유 상태 관리
_lock = threading.Lock()                        # 아래 딕셔너리 접근 보호
_stop_events: dict[int, threading.Event] = {}   # {robot_id: threading.Event}
_confirm_events: dict[int, threading.Event] = {} # {robot_id: threading.Event} — 작업 포인트 확인 대기
_run_info: dict[int, dict] = {}                 # {robot_id: 실행 상태 정보}
_move_locks: dict[int, threading.Lock] = {}     # {robot_id: 이동 명령 잠금} — 동시 이동 방지
_sessions: dict[str, requests.Session] = {}     # {robot_ip: requests.Session} — TCP 연결 재사용


# ─── 로봇별 HTTP 세션 / 이동 잠금 ────────────────────────────────────────────

def _get_session(ip: str) -> requests.Session:
    """robot IP별 HTTP 세션 반환 (TCP 연결 재사용)"""
    with _lock:
        if ip not in _sessions:
            s = requests.Session()
            adapter = requests.adapters.HTTPAdapter(pool_connections=1, pool_maxsize=1)
            s.mount("http://", adapter)
            _sessions[ip] = s
        return _sessions[ip]


def _get_move_lock(robot_id: int) -> threading.Lock:
    """robot_id별 이동 잠금 반환 (없으면 생성)"""
    with _lock:
        if robot_id not in _move_locks:
            _move_locks[robot_id] = threading.Lock()
        return _move_locks[robot_id]


def is_move_locked(robot_id: int) -> bool:
    """외부에서 해당 로봇이 이동 중인지 확인"""
    with _lock:
        ml = _move_locks.get(robot_id)
    if ml is None:
        return False
    return ml.locked()


# ─── AutoXing 로컬 API 호출 (HTTP — 이동 시작/취소만) ─────────────────────────

def _base_url(ip: str) -> str:
    return f"http://{ip}:{PORT}"


def send_move(ip: str, x: float, y: float, orientation: float,
              route_coords: str = "") -> tuple[bool, int, str]:
    """이동 명령 전송 → (success, move_id, error_message)
    route_coords: "x1,y1,x2,y2,..." 형식 — 지정 시 해당 경로를 엄격히 따름
    """
    session = _get_session(ip)
    # 경로 좌표가 있으면 along_given_route 타입 (직선 경로 엄수, 커브 최소화)
    # 없으면 standard 타입 (로봇 자율 경로 탐색)
    if route_coords:
        body = {
            "creator": "rcs",
            "type": "along_given_route",
            "target_x": x,
            "target_y": y,
            "target_ori": orientation,
            "route_coordinates": route_coords,
            "detour_tolerance": 0,
        }
    else:
        body = {
            "creator": "rcs",
            "type": "standard",
            "target_x": x,
            "target_y": y,
            "target_ori": orientation,
        }
    try:
        r = session.post(f"{_base_url(ip)}/chassis/moves", json=body, timeout=5)
        if r.status_code in (200, 201):
            return True, r.json().get("id"), ""
        return False, -1, f"HTTP {r.status_code}: {r.text}"
    except Exception as e:
        return False, -1, str(e)


FAIL_REASONS = {
    0: "없음",
    1: "알 수 없음",
    2: "맵 획득 실패",
    3: "출발점이 맵 밖",
    4: "도착점이 맵 밖",
    5: "출발점이 이동 불가 영역",
    6: "도착점이 이동 불가 영역",
    7: "출발점과 도착점이 동일",
    8: "글로벌 경로 확장 데이터 계산 실패",
    9: "경로 연결 안 됨",
    10: "경로 계산 타임아웃",
    11: "글로벌 경로 없음",
    12: "글로벌 경로에서 출발점 잡기 실패",
    13: "글로벌 경로에서 도착점 잡기 실패",
    14: "경로 계획 장시간 실패",
    15: "이동 타임아웃",
    16: "센서 데이터 이상 (로컬 장애물 회피 맵 오류)",
    17: "충전 케이블 연결됨",
    18: "회전 타임아웃",
    100: "충전 재시도 횟수 초과",
    101: "충전독 감지 오류",
    102: "충전독 도킹 신호 미수신",
    103: "유효하지 않은 충전독 위치",
    104: "이미 충전 중",
    105: "접촉 후 충전 전류 미감지",
    200: "유효하지 않은 캐비닛 위치",
    201: "캐비닛 감지 오류",
    202: "컨베이어 도킹 안 됨",
    203: "컨베이어 접근 안 됨",
    300: "엘리베이터 지점 점유됨",
    301: "엘리베이터 닫힘",
    302: "엘리베이터 지점 장시간 차단",
    303: "엘리베이터 지점 점유 감지 타임아웃",
    304: "엘리베이터 진입 진행 업데이트 타임아웃",
    400: "유효하지 않은 트랙 포인트",
    401: "트랙 시작점에서 너무 멀리 있음",
    500: "유효하지 않은 랙 감지 위치",
    501: "랙 감지 오류",
    502: "랙 도킹 재시도 횟수 초과",
    503: "언로드 지점 점유됨",
    504: "언로드 지점 도달 불가",
    505: "랙이 크게 이동됨",
    506: "잭이 올린 상태",
    507: "유효하지 않은 랙 영역 ID",
    508: "유효하지 않은 랙 영역 (랙 위치 없음)",
    509: "알 수 없는 랙 공간 상태",
    510: "랙 영역에 랙 없음",
    511: "랙 영역에서 도킹 실패",
    512: "랙 영역에 빈 공간 없음",
    513: "랙 영역에서 언로드 실패",
    600: "추적 대상 유실",
    700: "POI 감지 오류",
    701: "POI 도달 불가",
    702: "바코드 감지 오류",
    1000: "시스템 예외",
    1001: "서비스 호출 오류 (REST API)",
    1002: "내부 ASSERT 오류",
    1003: "작업 중 맵 변경됨",
    1004: "인터페이스 사용 중단됨",
}


def cancel_current_move(ip: str) -> bool:
    """현재 이동 취소"""
    session = _get_session(ip)
    try:
        r = session.patch(
            f"{_base_url(ip)}/chassis/moves/current",
            json={"state": "cancelled"},
            timeout=5,
        )
        return r.status_code == 200
    except Exception:
        return False


def cancel_and_verify(ip: str, max_wait: float = 5.0) -> bool:
    """이동 취소 후 실제로 cancelled 됐는지 확인"""
    session = _get_session(ip)

    # 1) 취소 명령 전송
    try:
        r = session.patch(
            f"{_base_url(ip)}/chassis/moves/current",
            json={"state": "cancelled"},
            timeout=5,
        )
        logger.info(f"[{ip}] cancel 응답: {r.status_code}")
    except Exception as e:
        logger.warning(f"[{ip}] cancel 요청 실패: {e}")

    # 2) 상태 확인
    deadline = time.time() + max_wait
    while time.time() < deadline:
        try:
            r = session.get(f"{_base_url(ip)}/chassis/moves/current", timeout=3)
            if r.status_code == 200:
                state = r.json().get("state", "")
                if state in ("cancelled", "succeeded", "failed", "idle"):
                    logger.info(f"[{ip}] cancel 확인 완료: {state}")
                    return True
                logger.info(f"[{ip}] cancel 대기 중... 현재 상태: {state}")
            elif r.status_code == 404:
                logger.info(f"[{ip}] cancel 확인: 진행 중 이동 없음 (404)")
                return True
        except Exception:
            pass
        time.sleep(0.5)

    logger.warning(f"[{ip}] cancel 확인 타임아웃 ({max_wait}초)")
    return False


# ─── WebSocket /planning_state 기반 이동 감시 ────────────────────────────────

def _create_planning_ws(ip: str):
    """로봇 /planning_state WebSocket 연결 생성"""
    ws_url = f"ws://{ip}:{PORT}/ws/v2/topics"
    ws = create_connection(ws_url, timeout=5)
    ws.send(json.dumps({"enable_topic": "/planning_state"}))
    ws.settimeout(WS_RECV_TIMEOUT)
    logger.info(f"[{ip}] /planning_state WebSocket 연결 성공")
    return ws


def _wait_for_move_ws(ws, move_id: int, ip: str,
                      stop_event: threading.Event) -> tuple[str, str]:
    """WebSocket /planning_state로 이동 완료 대기 → (result, detail)
    result: succeeded / failed / cancelled / timeout / ws_error
    - HTTP 폴링 없음! WebSocket 메시지만 읽음
    - action_id로 우리 이동인지 필터링
    """
    start = time.time()
    last_state = ""
    last_remaining = None
    last_msg_time = time.time()   # 마지막 메시지 수신 시각

    while (time.time() - start) < MOVE_TIMEOUT:
        if stop_event.is_set():
            cancel_current_move(ip)
            return "cancelled", ""

        # WebSocket 무응답 감지 — 일정 시간 메시지 없으면 연결 끊김 판단
        silence = time.time() - last_msg_time
        if silence > WS_SILENCE_LIMIT:
            logger.error(f"[Move {move_id}] WS {silence:.0f}초 무응답 — 연결 끊김 판단")
            return "ws_error", f"WebSocket {silence:.0f}초 무응답"

        # WebSocket에서 메시지 수신
        try:
            raw = ws.recv()
        except (WebSocketException, TimeoutError, OSError):
            # recv timeout — 정상, 다시 대기
            continue

        if not raw:
            continue

        try:
            pkt = json.loads(raw)
        except json.JSONDecodeError:
            continue

        if pkt.get("topic") != "/planning_state":
            last_msg_time = time.time()  # 다른 토픽이라도 연결은 살아있음
            continue

        last_msg_time = time.time()  # planning_state 메시지 수신
        state = str(pkt.get("move_state", "")).lower()
        action_id = pkt.get("action_id")
        remaining = pkt.get("remaining_distance")
        stuck = pkt.get("stuck_state", "")

        # 상태 변경 시 로그
        if state != last_state or remaining != last_remaining:
            logger.info(f"[Move {move_id}] WS: {last_state or '(시작)'} → {state} "
                        f"(action={action_id}, 거리={remaining}, stuck={stuck})")
            last_state = state
            last_remaining = remaining

        # action_id가 있으면 우리 이동인지 확인
        if action_id is not None and action_id != move_id:
            continue

        # 종료 상태 처리
        if state == "succeeded":
            return "succeeded", ""
        elif state == "failed":
            reason = pkt.get("fail_reason", -1)
            reason_text = FAIL_REASONS.get(reason, f"코드 {reason}")
            detail = f"[{reason}] {reason_text}"
            logger.error(f"[Move {move_id}] WS 실패: {detail}")
            return "failed", detail
        elif state == "cancelled":
            return "cancelled", ""

    logger.warning(f"[Move {move_id}] WS 타임아웃 ({MOVE_TIMEOUT}초)")
    cancel_current_move(ip)
    return "timeout", ""


def _wait_for_move_http(ip: str, move_id: int,
                        stop_event: threading.Event) -> tuple[str, str]:
    """HTTP 폴링 폴백 — WebSocket 연결 불가 시에만 사용"""
    elapsed = 0.0
    last_state = ""
    session = _get_session(ip)
    poll_interval = 3.0  # HTTP 폴백은 간격 넓게

    while elapsed < MOVE_TIMEOUT:
        if stop_event.is_set():
            cancel_current_move(ip)
            return "cancelled", ""

        try:
            r = session.get(f"{_base_url(ip)}/chassis/moves/{move_id}", timeout=5)
            if r.status_code == 200:
                data = r.json()
                state = data.get("state", "unknown")

                if state != last_state:
                    logger.info(f"[Move {move_id}] HTTP: {last_state or '(시작)'} → {state}")
                    last_state = state

                if state == "succeeded":
                    return "succeeded", ""
                elif state == "failed":
                    reason = data.get("fail_reason", -1)
                    reason_text = FAIL_REASONS.get(reason, f"코드 {reason}")
                    detail = f"[{reason}] {reason_text}"
                    return "failed", detail
                elif state == "cancelled":
                    return "cancelled", ""
        except Exception as e:
            logger.warning(f"[Move {move_id}] HTTP 폴링 오류: {e}")

        time.sleep(poll_interval)
        elapsed += poll_interval

    cancel_current_move(ip)
    return "timeout", ""


# ─── 충전 상태 확인 ────────────────────────────────────────────────────────────

def _is_charging(ip: str) -> bool:
    """로봇이 현재 충전 중인지 WebSocket으로 확인"""
    ws = None
    try:
        ws_url = f"ws://{ip}:{PORT}/ws/v2/topics"
        ws = create_connection(ws_url, timeout=5)
        ws.send(json.dumps({"enable_topic": "/planning_state"}))
        ws.send(json.dumps({"enable_topic": "/battery_state"}))
        ws.settimeout(3.0)

        planning = {}
        battery = {}
        deadline = time.time() + 5

        while time.time() < deadline:
            try:
                raw = ws.recv()
                pkt = json.loads(raw)
                topic = pkt.get("topic")
                if topic == "/planning_state":
                    planning = pkt
                elif topic in ("/detailed_battery_state", "/battery_state"):
                    battery = pkt
                if planning and battery:
                    break
            except (WebSocketException, TimeoutError, OSError):
                continue

        power_supply_status = str(battery.get("power_supply_status", "")).lower()
        action_type = str(planning.get("action_type", "")).lower()
        move_state = str(planning.get("move_state", "")).lower()

        is_chg = (
            power_supply_status in {"charging", "full"}
            or (action_type == "charge" and move_state in {"idle", "none", "succeeded"})
        )
        logger.info(f"[{ip}] 충전 상태 확인: power={power_supply_status}, "
                    f"action={action_type}, move={move_state} → {'충전 중' if is_chg else '충전 아님'}")
        return is_chg
    except Exception as e:
        logger.warning(f"[{ip}] 충전 상태 확인 실패: {e} — 진입 경로 생략")
        return False
    finally:
        if ws:
            try:
                ws.close()
            except Exception:
                pass


# ─── 구간 그룹화 ────────────────────────────────────────────────────────────────

def _build_segments(pois: list, stop_names: set[str]) -> list[dict]:
    """POI 목록을 '구간(segment)' 단위로 그룹화
    - stop_names에 포함된 POI에서만 정지 (작업 포인트)
    - 나머지 POI는 경유 좌표(route_coordinates)로 통과
    - stop_names가 비어있으면 모든 POI에서 정지 (기존 동작)

    반환: [{"target": poi, "waypoints": [poi, ...], "route_coords": "x,y,x,y,..."}]
    """
    if not stop_names:
        # stop_names 미지정 → 모든 POI에서 정지 (기존 동작)
        segments = []
        for i, poi in enumerate(pois):
            seg = {"target": poi, "waypoints": [], "route_coords": ""}
            if i > 0:
                prev = pois[i - 1]
                px = prev.world_x if prev.world_x is not None else prev.x
                py = prev.world_y if prev.world_y is not None else prev.y
                tx = poi.world_x if poi.world_x is not None else poi.x
                ty = poi.world_y if poi.world_y is not None else poi.y
                seg["route_coords"] = f"{px},{py},{tx},{ty}"
            segments.append(seg)
        return segments

    # stop_names 지정 → 구간별 그룹화
    segments = []
    current_waypoints = []

    for poi in pois:
        if poi.name in stop_names:
            # 작업 포인트 → 이 POI가 구간의 목표
            # route_coords: 경유 POI들 + 목표 POI 좌표를 이어서 만듬
            coords_parts = []
            for wp in current_waypoints:
                wx = wp.world_x if wp.world_x is not None else wp.x
                wy = wp.world_y if wp.world_y is not None else wp.y
                coords_parts.extend([str(wx), str(wy)])
            tx = poi.world_x if poi.world_x is not None else poi.x
            ty = poi.world_y if poi.world_y is not None else poi.y
            coords_parts.extend([str(tx), str(ty)])

            segments.append({
                "target": poi,
                "waypoints": current_waypoints[:],
                "route_coords": ",".join(coords_parts) if len(coords_parts) > 2 else "",
            })
            current_waypoints = []
        else:
            # 경유 포인트 → 다음 작업 포인트까지 모아둠
            current_waypoints.append(poi)

    # 마지막 작업 포인트 이후 남은 경유 POI → 다음 루프 첫 구간에 붙임
    # (이건 _task_runner에서 루프마다 처리)
    if current_waypoints:
        segments.append({
            "target": None,
            "waypoints": current_waypoints[:],
            "route_coords": "",
            "_trailing": True,  # 루프 끝 잔여 경유점 표시
        })

    return segments


# ─── 무한반복 실행 엔진 ─────────────────────────────────────────────────────────

def _task_runner(robot_id: int, robot_ip: str, poi_names: list[str],
                 stop_event: threading.Event, stop_names: list[str] | None = None,
                 entry_poi_names: list[str] | None = None):
    """백그라운드 무한반복 스레드
    1) WebSocket /planning_state 연결 (실시간 상태 감시)
    2) entry_poi_names가 있으면 진입 경로를 1회 통과 (충전소→작업구역)
    3) DB에서 POI 좌표 조회 → 구간(segment) 단위로 이동 → 무한 반복
    4) stop_names에 포함된 POI에서만 정지, 나머지는 경유 (통과)
    """
    db = None
    ws = None
    move_lock = _get_move_lock(robot_id)
    stop_set = set(stop_names) if stop_names else set()

    try:
        db = SessionLocal()

        # WebSocket 연결 시도
        try:
            ws = _create_planning_ws(robot_ip)
        except Exception as e:
            logger.warning(f"[Robot {robot_id}] WebSocket 연결 실패 — HTTP 폴백 사용: {e}")

        # DB에서 POI 좌표 조회
        pois = []
        for name in poi_names:
            poi = db.query(MapPOI).filter(
                MapPOI.name == name,
                MapPOI.is_active == True,
            ).first()
            if not poi:
                logger.error(f"[Robot {robot_id}] POI '{name}' 을 찾을 수 없습니다")
                with _lock:
                    _run_info[robot_id] = {"status": "error", "message": f"POI '{name}' 없음"}
                return
            pois.append(poi)

        # ── 진입 경로 처리 (충전소 → 작업구역, 충전 상태일 때만 1회) ──
        if entry_poi_names and _is_charging(robot_ip):
            entry_pois = []
            for name in entry_poi_names:
                poi = db.query(MapPOI).filter(
                    MapPOI.name == name,
                    MapPOI.is_active == True,
                ).first()
                if not poi:
                    logger.error(f"[Robot {robot_id}] 진입 POI '{name}' 을 찾을 수 없습니다")
                    with _lock:
                        _run_info[robot_id] = {"status": "error", "message": f"진입 POI '{name}' 없음"}
                    return
                entry_pois.append(poi)

            logger.info(f"[Robot {robot_id}] 진입 경로 시작: {[p.name for p in entry_pois]}")

            # 진입 POI를 순서대로 경유하여 마지막 진입 POI까지 이동
            # route_coordinates: 모든 진입 POI 좌표를 이어서 한 번에 이동
            entry_target = entry_pois[-1]
            entry_coords_parts = []
            for ep in entry_pois:
                ex = ep.world_x if ep.world_x is not None else ep.x
                ey = ep.world_y if ep.world_y is not None else ep.y
                entry_coords_parts.extend([str(ex), str(ey)])

            etx = entry_target.world_x if entry_target.world_x is not None else entry_target.x
            ety = entry_target.world_y if entry_target.world_y is not None else entry_target.y
            et_angle = entry_target.angle if entry_target.angle is not None else 0.0
            entry_route_coords = ",".join(entry_coords_parts) if len(entry_coords_parts) > 2 else ""

            with _lock:
                _run_info[robot_id] = {
                    "status": "running",
                    "current_poi": entry_target.name,
                    "message": "진입 경로 이동 중",
                }

            with move_lock:
                ok, move_id, err = send_move(
                    robot_ip, etx, ety, et_angle, route_coords=entry_route_coords)
                if not ok:
                    logger.error(f"[Robot {robot_id}] 진입 경로 이동 명령 실패: {err}")
                    with _lock:
                        _run_info[robot_id] = {"status": "error", "message": err}
                    return

                logger.info(f"[Robot {robot_id}] 진입 경로 Move {move_id} 전송 완료")

                if ws:
                    try:
                        result, detail = _wait_for_move_ws(ws, move_id, robot_ip, stop_event)
                        if result == "ws_error":
                            try:
                                ws.close()
                            except Exception:
                                pass
                            ws = None
                    except (WebSocketException, OSError) as e:
                        try:
                            ws.close()
                        except Exception:
                            pass
                        ws = None
                        result = "ws_error"
                        detail = str(e)
                else:
                    result, detail = _wait_for_move_http(robot_ip, move_id, stop_event)

            if result == "cancelled":
                logger.info(f"[Robot {robot_id}] 진입 경로 중 사용자 정지")
                with _lock:
                    _run_info[robot_id] = {"status": "stopped"}
                return
            if result in ("failed", "timeout", "ws_error"):
                logger.error(f"[Robot {robot_id}] 진입 경로 이동 실패 ({result}) — {detail}")
                with _lock:
                    _run_info[robot_id] = {"status": "error", "message": f"진입 경로 실패: {result} | {detail}"}
                return

            logger.info(f"[Robot {robot_id}] 진입 경로 완료 — 루프 작업 시작")

        # 구간 생성
        segments = _build_segments(pois, stop_set)

        # 잔여 경유점 처리: 마지막 구간이 _trailing이면 첫 구간 앞에 붙임
        trailing_waypoints = []
        if segments and segments[-1].get("_trailing"):
            trailing_seg = segments.pop()
            trailing_waypoints = trailing_seg["waypoints"]

        if not segments:
            logger.error(f"[Robot {robot_id}] 작업 포인트가 없습니다 (stop_names에 해당하는 POI 없음)")
            with _lock:
                _run_info[robot_id] = {"status": "error", "message": "작업 포인트 없음"}
            return

        stop_poi_names = [s["target"].name for s in segments]
        logger.info(f"[Robot {robot_id}] 무한반복 시작 — 전체 POI {len(pois)}개, "
                    f"작업 포인트: {stop_poi_names}, "
                    f"경유 포인트: {[p.name for p in pois if p.name not in stop_set]} "
                    f"(감시: {'WebSocket' if ws else 'HTTP 폴백'})")

        loop = 0
        while not stop_event.is_set():
            loop += 1
            logger.info(f"[Robot {robot_id}] ── 루프 {loop}회 시작 ──")

            for seg_idx, seg in enumerate(segments):
                if stop_event.is_set():
                    break

                target = seg["target"]
                waypoints = seg["waypoints"]

                # 루프 2회차부터 + 첫 구간: trailing 경유점을 앞에 붙임
                if seg_idx == 0 and trailing_waypoints:
                    if loop > 1:
                        waypoints = trailing_waypoints + waypoints
                    else:
                        # 루프 1회차 첫 구간은 trailing 없음 (아직 안 돌았으니까)
                        pass

                # route_coordinates 생성: 경유점들 + 목표점
                coords_parts = []
                for wp in waypoints:
                    wx = wp.world_x if wp.world_x is not None else wp.x
                    wy = wp.world_y if wp.world_y is not None else wp.y
                    coords_parts.extend([str(wx), str(wy)])

                tx = target.world_x if target.world_x is not None else target.x
                ty = target.world_y if target.world_y is not None else target.y
                t_angle = target.angle if target.angle is not None else 0.0
                coords_parts.extend([str(tx), str(ty)])
                route_coords = ",".join(coords_parts) if len(coords_parts) > 2 else ""

                wp_names = [w.name for w in waypoints]
                # 상태 업데이트
                with _lock:
                    _run_info[robot_id] = {
                        "status": "running",
                        "loop": loop,
                        "current_poi": target.name,
                        "current_segment": seg_idx + 1,
                        "total_segments": len(segments),
                        "waypoints": wp_names,
                        "poi_list": [p.name for p in pois],
                    }

                logger.info(f"[Robot {robot_id}] [구간 {seg_idx + 1}/{len(segments)}] "
                            f"{'→'.join(wp_names + [target.name])} "
                            f"(target={tx},{ty}, route={route_coords})")

                # 이동 실행 (최대 3회 재시도)
                max_retries = 3
                result = ""
                detail = ""

                for attempt in range(1, max_retries + 1):
                    if stop_event.is_set():
                        break

                    with move_lock:
                        if attempt > 1:
                            logger.info(f"[Robot {robot_id}] 이동 재시도 {attempt}/{max_retries}")
                            cancel_and_verify(robot_ip)
                            logger.info(f"[Robot {robot_id}] 로봇 복구 대기 {RECOVERY_DELAY}초...")
                            time.sleep(RECOVERY_DELAY)

                            if ws is None:
                                try:
                                    ws = _create_planning_ws(robot_ip)
                                except Exception:
                                    pass

                        ok, move_id, err = send_move(
                            robot_ip, tx, ty, t_angle, route_coords=route_coords)
                        if not ok:
                            logger.error(f"[Robot {robot_id}] 이동 명령 실패: {err}")
                            with _lock:
                                _run_info[robot_id] = {"status": "error", "message": err}
                            return

                        logger.info(f"[Robot {robot_id}] Move {move_id} 전송 완료")

                        # WebSocket 또는 HTTP 폴백으로 이동 완료 대기
                        if ws:
                            try:
                                result, detail = _wait_for_move_ws(
                                    ws, move_id, robot_ip, stop_event)
                                if result == "ws_error":
                                    logger.warning(f"[Robot {robot_id}] WS 무응답 — 연결 재설정")
                                    try:
                                        ws.close()
                                    except Exception:
                                        pass
                                    ws = None
                            except (WebSocketException, OSError) as e:
                                logger.warning(f"[Robot {robot_id}] WS 끊김: {e}")
                                try:
                                    ws.close()
                                except Exception:
                                    pass
                                ws = None
                                result = "ws_error"
                                detail = str(e)
                        else:
                            result, detail = _wait_for_move_http(
                                robot_ip, move_id, stop_event)

                    logger.info(f"[Robot {robot_id}] 이동 결과: {result} {detail}")

                    if result in ("failed", "ws_error") and attempt < max_retries:
                        logger.warning(f"[Robot {robot_id}] 이동 {result} — 재시도 예정")
                        continue
                    break

                if result == "cancelled":
                    break
                if result in ("failed", "timeout", "ws_error"):
                    logger.error(f"[Robot {robot_id}] 이동 최종 실패 ({result}) — {detail}")
                    with _lock:
                        _run_info[robot_id] = {
                            "status": "error",
                            "message": f"이동 실패: {result} | {detail}",
                        }
                    return

                # ── 작업 포인트 도착 → 태블릿 확인 대기 ──
                if result == "succeeded" and stop_set and target.name in stop_set:
                    logger.info(f"[Robot {robot_id}] 작업 포인트 '{target.name}' 도착 — 태블릿 확인 대기")
                    confirm_event = threading.Event()
                    with _lock:
                        _confirm_events[robot_id] = confirm_event
                        _run_info[robot_id] = {
                            "status": "waiting_confirmation",
                            "loop": loop,
                            "current_poi": target.name,
                            "current_segment": seg_idx + 1,
                            "total_segments": len(segments),
                            "poi_list": [p.name for p in pois],
                        }

                    # 확인 또는 정지 신호 대기 (1초 간격 체크)
                    while not confirm_event.is_set():
                        if stop_event.is_set():
                            break
                        confirm_event.wait(timeout=1.0)

                    with _lock:
                        _confirm_events.pop(robot_id, None)

                    if stop_event.is_set():
                        break

                    logger.info(f"[Robot {robot_id}] 작업 포인트 '{target.name}' 확인 완료 — 다음 구간 진행")

        # stop_event로 중단됨
        logger.info(f"[Robot {robot_id}] 사용자 정지 — {loop}회 완료")
        with _lock:
            _run_info[robot_id] = {"status": "stopped", "loop": loop}

    except Exception as e:
        logger.exception(f"[Robot {robot_id}] 예외: {e}")
        with _lock:
            _run_info[robot_id] = {"status": "error", "message": str(e)}
    finally:
        if ws:
            try:
                ws.close()
            except Exception:
                pass
        if db:
            db.close()
        with _lock:
            _stop_events.pop(robot_id, None)
            _confirm_events.pop(robot_id, None)
        logger.info(f"[Robot {robot_id}] 스레드 종료")


# ─── 공개 인터페이스 ────────────────────────────────────────────────────────────

def start_loop(robot_id: int, robot_ip: str, poi_names: list[str],
               stop_names: list[str] | None = None,
               entry_poi_names: list[str] | None = None) -> tuple[bool, str]:
    """POI 이름 목록을 받아 무한반복 실행 시작 (스레드 안전)
    stop_names: 작업 포인트 (정지할 POI). 비어있으면 모든 POI에서 정지
    entry_poi_names: 진입 경로 POI (충전소→작업구역, 최초 1회만 통과)
    """
    with _lock:
        old_event = _stop_events.get(robot_id)
        if old_event:
            if old_event.is_set():
                logger.info(f"[Robot {robot_id}] 이전 스레드 정리 중 — 강제 제거 후 재시작")
                _stop_events.pop(robot_id, None)
            else:
                return False, "이미 실행 중입니다"
        if not poi_names:
            return False, "POI 목록이 비어 있습니다"

        stop_event = threading.Event()
        _stop_events[robot_id] = stop_event
        _run_info[robot_id] = {"status": "starting", "poi_list": poi_names}

    # 새 작업 시작 전 로봇의 잔여 이동 취소 + 확인
    cancel_and_verify(robot_ip)

    t = threading.Thread(
        target=_task_runner,
        args=(robot_id, robot_ip, poi_names, stop_event, stop_names, entry_poi_names),
        daemon=True,
        name=f"loop-robot-{robot_id}",
    )
    t.start()
    logger.info(f"[Robot {robot_id}] 스레드 시작 — 진입: {entry_poi_names}, POI: {poi_names}, 작업포인트: {stop_names}")
    return True, "무한반복 작업이 시작되었습니다"


def confirm_loop(robot_id: int) -> tuple[bool, str]:
    """작업 포인트 확인 → 다음 구간 진행 (스레드 안전)
    로봇 태블릿에서 호출하여 작업 포인트 대기 해제
    """
    with _lock:
        event = _confirm_events.get(robot_id)
        if not event:
            info = _run_info.get(robot_id, {})
            if info.get("status") != "waiting_confirmation":
                return False, "확인 대기 중인 작업이 없습니다"
            return False, "확인 이벤트를 찾을 수 없습니다"
    event.set()
    logger.info(f"[Robot {robot_id}] 태블릿 확인 신호 수신")
    return True, "확인 완료 — 다음 구간으로 진행합니다"


def stop_loop(robot_id: int, robot_ip: str = "") -> tuple[bool, str]:
    """실행 중인 무한반복 정지 (스레드 안전)"""
    with _lock:
        event = _stop_events.get(robot_id)
        if not event:
            info = _run_info.get(robot_id, {})
            if info.get("status") in ("error", "stopped"):
                _run_info.pop(robot_id, None)
            if robot_ip:
                cancel_current_move(robot_ip)
            return False, "실행 중인 작업이 없습니다"
    event.set()
    if robot_ip:
        cancel_current_move(robot_ip)
    logger.info(f"[Robot {robot_id}] 정지 요청 전송 + 이동 취소")
    return True, "정지 요청을 전송했습니다"


def get_loop_status(robot_id: int) -> dict:
    """실행 상태 조회 (스레드 안전)"""
    with _lock:
        running = robot_id in _stop_events
        info = _run_info.get(robot_id)
    if running:
        return info if info else {"status": "running"}
    if info:
        return info
    return {"status": "idle"}


def is_running(robot_id: int) -> bool:
    with _lock:
        return robot_id in _stop_events
