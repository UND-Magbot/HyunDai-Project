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
from app.models.map import MapPOI, RobotMap
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
_graceful_stop_events: dict[int, threading.Event] = {}  # {robot_id: threading.Event} — CURPOS1 도착 후 정지
_confirm_events: dict[int, threading.Event] = {} # {robot_id: threading.Event} — 작업 포인트 확인 대기
_run_info: dict[int, dict] = {}                 # {robot_id: 실행 상태 정보}
_move_locks: dict[int, threading.Lock] = {}     # {robot_id: 이동 명령 잠금} — 동시 이동 방지
_sessions: dict[str, requests.Session] = {}     # {robot_ip: requests.Session} — TCP 연결 재사용
_charging_robots: set[int] = set()              # 배터리 부족으로 충전소 이동한 로봇 ID
_stuck_states: dict[int, bool] = {}             # {robot_id: True=장애물 감지}


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


def _get_docking_point_coords(ip: str, charger_name: str) -> tuple[float, float, float] | None:
    """로봇 맵 오버레이에서 충전소의 도킹포인트 좌표 조회.
    반환: (x, y, yaw) 또는 None (조회 실패)"""
    try:
        session = _get_session(ip)
        r = session.get(f"{_base_url(ip)}/chassis/current-map", timeout=5)
        if r.status_code != 200:
            return None
        map_id = r.json().get("id")
        if not map_id:
            return None
        r = session.get(f"{_base_url(ip)}/maps/{map_id}", timeout=5)
        if r.status_code != 200:
            return None
        overlays = json.loads(r.json().get("overlays", "{}"))
        features = overlays.get("features", [])

        # 충전소(type=9)에서 도킹포인트 ID 찾기
        docking_point_id = None
        for feat in features:
            props = feat.get("properties", {})
            if str(props.get("type")) == "9" and props.get("name") == charger_name:
                docking_point_id = props.get("dockingPointId")
                break

        if not docking_point_id:
            logger.warning(f"[{ip}] 충전소 '{charger_name}' 도킹포인트 없음")
            return None

        # 도킹포인트(type=36) 좌표 조회
        for feat in features:
            if feat.get("id") == docking_point_id:
                coords = feat.get("geometry", {}).get("coordinates", [])
                props = feat.get("properties", {})
                yaw = float(props.get("yaw", 0))
                if len(coords) >= 2:
                    logger.info(f"[{ip}] '{charger_name}' 도킹포인트: "
                                f"({coords[0]}, {coords[1]}, yaw={yaw})")
                    return (coords[0], coords[1], yaw)

        logger.warning(f"[{ip}] 도킹포인트 ID '{docking_point_id}' feature 없음")
        return None
    except Exception as e:
        logger.warning(f"[{ip}] 도킹포인트 좌표 조회 실패: {e}")
        return None


def send_charge(ip: str, retry_count: int = 3,
                charger_name: str | None = None) -> tuple[bool, str]:
    """충전소 이동+도킹 명령 전송 → (success, message)
    charger_name: 충전소 이름 (예: "C3") — 도킹포인트 좌표를 target_x/target_y로 전달.
    None이면 좌표 미지정 (로봇 기본 충전소 사용).
    """
    session = _get_session(ip)
    body: dict = {
        "creator": "rcs",
        "type": "charge",
        "charge_retry_count": retry_count,
    }
    # 충전소 지정 시: 도킹포인트 좌표를 target_x/target_y로 전달
    if charger_name:
        coords = _get_docking_point_coords(ip, charger_name)
        if coords:
            body["target_x"] = coords[0]
            body["target_y"] = coords[1]
            body["target_ori"] = coords[2]
            logger.info(f"[{ip}] 충전 목표: '{charger_name}' "
                        f"({coords[0]}, {coords[1]}, yaw={coords[2]})")
    try:
        r = session.post(f"{_base_url(ip)}/chassis/moves", json=body, timeout=5)
        if r.status_code in (200, 201):
            move_id = r.json().get("id", -1)
            return True, f"충전소 이동 시작 (move_id={move_id})"
        logger.error(f"[send_charge] HTTP {r.status_code}: {r.text}")
        return False, "충전소 이동에 실패했습니다."
    except Exception as e:
        logger.error(f"[send_charge] 예외: {e}")
        return False, "충전소 이동에 실패했습니다."


def start_charge_route(robot_id: int, robot_ip: str,
                       route_poi_names: list[str],
                       charger_name: str | None = None) -> tuple[bool, str]:
    """충전소 이동 (경유 경로 포함) — 백그라운드 스레드 시작"""
    t = threading.Thread(
        target=_charge_route_runner,
        args=(robot_id, robot_ip, route_poi_names, charger_name),
        daemon=True,
        name=f"charge-robot-{robot_id}",
    )
    t.start()
    logger.info(f"[Robot {robot_id}] 충전 경로 스레드 시작: {route_poi_names}")
    return True, "충전소 이동 경로 시작"


def _charge_route_runner(robot_id: int, robot_ip: str,
                         route_poi_names: list[str],
                         charger_name: str | None = None):
    """백그라운드: 경유 POI 순차 이동 → 충전 명령"""
    ws = None
    move_lock = _get_move_lock(robot_id)
    stop_event = threading.Event()  # 충전 경로는 취소 미지원 (더미)

    try:
        # POI 좌표 조회 (DB 세션 즉시 반환)
        route_pois = []
        db = SessionLocal()
        try:
            # ── 활성 맵 ID 자동 감지 (중복 POI 이름 방지) ──
            first_poi = db.query(MapPOI).join(RobotMap).filter(
                MapPOI.name == route_poi_names[0],
                MapPOI.is_active == True,
                RobotMap.is_active == True,
            ).order_by(RobotMap.id.desc()).first()
            if not first_poi:
                logger.error(f"[Robot {robot_id}] 충전 경로 POI '{route_poi_names[0]}' 없음")
                return
            target_map_id = first_poi.map_id

            for name in route_poi_names:
                poi = db.query(MapPOI).filter(
                    MapPOI.name == name, MapPOI.is_active == True,
                    MapPOI.map_id == target_map_id,
                ).first()
                if not poi:
                    logger.error(f"[Robot {robot_id}] 충전 경로 POI '{name}' 없음 (map_id={target_map_id})")
                    return
                db.expunge(poi)
                route_pois.append(poi)
        finally:
            db.close()

        if not route_pois:
            send_charge(robot_ip, charger_name=charger_name)
            return

        # WebSocket 연결
        try:
            ws = _create_planning_ws(robot_ip)
        except Exception as e:
            logger.warning(f"[Robot {robot_id}] 충전 경로 WS 연결 실패: {e}")

        # route_coordinates로 마지막 POI까지 한 번에 이동
        target = route_pois[-1]
        coords_parts = []
        for p in route_pois:
            px = p.world_x if p.world_x is not None else p.x
            py = p.world_y if p.world_y is not None else p.y
            coords_parts.extend([str(px), str(py)])

        tx = target.world_x if target.world_x is not None else target.x
        ty = target.world_y if target.world_y is not None else target.y
        t_angle = target.angle if target.angle is not None else 0.0
        route_coords = ",".join(coords_parts) if len(coords_parts) > 2 else ""

        logger.info(f"[Robot {robot_id}] 충전 경로 이동: "
                    f"{'→'.join(p.name for p in route_pois)}")

        with _lock:
            _run_info[robot_id] = {
                "status": "charging_route",
                "message": "충전소 이동 중",
            }

        with move_lock:
            ok, move_id, err = send_move(
                robot_ip, tx, ty, t_angle, route_coords=route_coords)
            if not ok:
                logger.error(f"[Robot {robot_id}] 충전 경로 이동 명령 실패: {err}")
                with _lock:
                    _run_info[robot_id] = {
                        "status": "error",
                        "message": "충전 경로 이동에 실패했습니다.",
                        "error_code": "ROBOT-005",
                        "description": "_charge_route_runner() — 충전 경로 이동 명령 실패",
                    }
                return

            logger.info(f"[Robot {robot_id}] 충전 경로 Move {move_id} 전송")

            if ws:
                try:
                    result, detail = _wait_for_move_ws(
                        ws, move_id, robot_ip, stop_event)
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
                result, detail = _wait_for_move_http(
                    robot_ip, move_id, stop_event)

        logger.info(f"[Robot {robot_id}] 충전 경로 이동 결과: {result} {detail}")

        if result != "succeeded":
            logger.error(f"[Robot {robot_id}] 충전 경로 실패 — 충전 명령 취소")
            with _lock:
                _run_info[robot_id] = {
                    "status": "error",
                    "message": f"충전 경로 이동에 실패했습니다. ({detail})",
                    "error_code": "ROBOT-005",
                    "description": "_charge_route_runner() — 충전 경로 이동 실패",
                }
            return

        # 경로 도착 → 충전 명령 전송
        with _lock:
            _run_info[robot_id] = {
                "status": "charging",
                "message": "충전 중",
            }

        time.sleep(1)
        ok, msg = send_charge(robot_ip, charger_name=charger_name)
        logger.info(f"[Robot {robot_id}] 충전 명령 (charger={charger_name}): ok={ok}, {msg}")

        if ok:
            with _lock:
                _run_info[robot_id] = {
                    "status": "charging",
                    "message": "충전 중",
                }
        else:
            with _lock:
                _run_info[robot_id] = {
                    "status": "error",
                    "message": "충전 명령에 실패했습니다.",
                    "error_code": "ROBOT-006",
                    "description": "_charge_route_runner() — 충전 명령 실패",
                }

    except Exception as e:
        logger.exception(f"[Robot {robot_id}] 충전 경로 예외: {e}")
        with _lock:
            _run_info[robot_id] = {
                "status": "error",
                "message": "충전 경로 실행 중 오류가 발생했습니다.",
                "error_code": "ROBOT-005",
                "description": "_charge_route_runner() — 충전 경로 예외",
            }
    finally:
        if ws:
            try:
                ws.close()
            except Exception:
                pass
        # DB 세션은 POI 조회 직후 이미 닫힘
        logger.info(f"[Robot {robot_id}] 충전 경로 스레드 종료")


def send_move(ip: str, x: float, y: float, orientation: float,
              route_coords: str = "",
              target_accuracy: float | None = None) -> tuple[bool, int, str]:
    """이동 명령 전송 → (success, move_id, error_message)
    route_coords: "x1,y1,x2,y2,..." 형식 — 지정 시 해당 경로를 엄격히 따름
    target_accuracy: 도착 인식 반경(m) — 작을수록 정확한 위치에 도착해야 완료
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
    if target_accuracy is not None:
        body["target_accuracy"] = target_accuracy
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
                      stop_event: threading.Event,
                      robot_id: int | None = None,
                      cancel_on_stuck: bool = False) -> tuple[str, str]:
    """WebSocket /planning_state로 이동 완료 대기 → (result, detail)
    result: succeeded / failed / cancelled / timeout / ws_error / stuck
    - HTTP 폴링 없음! WebSocket 메시지만 읽음
    - action_id로 우리 이동인지 필터링
    - robot_id 지정 시 stuck_state를 _stuck_states에 추적
    - cancel_on_stuck=True: 장애물 감지 시 이동 취소 후 'stuck' 반환
    """
    start = time.time()
    last_state = ""
    last_remaining = None
    last_msg_time = time.time()   # 마지막 메시지 수신 시각
    stuck_first_time = None       # 장애물 처음 감지 시각

    while (time.time() - start) < MOVE_TIMEOUT:
        if stop_event.is_set():
            cancel_current_move(ip)
            if robot_id is not None:
                with _lock:
                    _stuck_states[robot_id] = False
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

        # stuck_state 추적 (robot_id가 있을 때만)
        if robot_id is not None:
            is_stuck = bool(stuck) and str(stuck) not in ("0", "", "none", "None")
            with _lock:
                _stuck_states[robot_id] = is_stuck

            # 장애물 감지 시 즉시 취소 (cancel_on_stuck 모드)
            if cancel_on_stuck and is_stuck:
                if stuck_first_time is None:
                    stuck_first_time = time.time()
                    logger.info(f"[Move {move_id}] 장애물 감지 — 이동 취소")
                    cancel_current_move(ip)
                    return "stuck", "장애물 감지"
            else:
                stuck_first_time = None

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
            if robot_id is not None:
                with _lock:
                    _stuck_states[robot_id] = False
            return "succeeded", ""
        elif state == "failed":
            reason = pkt.get("fail_reason", -1)
            reason_text = FAIL_REASONS.get(reason, f"코드 {reason}")
            detail = f"[{reason}] {reason_text}"
            logger.error(f"[Move {move_id}] WS 실패: {detail}")
            if robot_id is not None:
                with _lock:
                    _stuck_states[robot_id] = False
            return "failed", detail
        elif state == "cancelled":
            if robot_id is not None:
                with _lock:
                    _stuck_states[robot_id] = False
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


# ─── 배터리 잔량 조회 ──────────────────────────────────────────────────────────

def _get_battery_percentage(ip: str, timeout: float = 5.0) -> float | None:
    """WebSocket으로 로봇의 현재 배터리 잔량(%) 조회
    반환: 0~100 범위의 float, 실패 시 None
    """
    ws = None
    try:
        ws_url = f"ws://{ip}:{PORT}/ws/v2/topics"
        ws = create_connection(ws_url, timeout=5)
        ws.send(json.dumps({"enable_topic": "/battery_state"}))
        ws.send(json.dumps({"enable_topic": "/detailed_battery_state"}))
        ws.settimeout(3.0)

        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                raw = ws.recv()
                pkt = json.loads(raw)
                topic = pkt.get("topic")
                if topic in ("/detailed_battery_state", "/battery_state"):
                    percentage = pkt.get("percentage")
                    if isinstance(percentage, (int, float)):
                        if percentage <= 1:
                            percentage = percentage * 100
                        return float(percentage)
            except (WebSocketException, TimeoutError, OSError):
                continue

        return None
    except Exception as e:
        logger.warning(f"[{ip}] 배터리 조회 실패: {e}")
        return None
    finally:
        if ws:
            try:
                ws.close()
            except Exception:
                pass


# ─── 충전 설정 조회 ───────────────────────────────────────────────────────────

def _get_charging_config(db, robot_id: int) -> tuple[int, "MapPOI | None"]:
    """DB에서 로봇의 min_battery 및 충전소 POI 조회"""
    robot = db.query(Robot).filter(Robot.id == robot_id).first()
    if not robot:
        return 20, None

    charging_poi = None
    if robot.charging_id:
        charging_poi = db.query(MapPOI).filter(
            MapPOI.id == robot.charging_id,
            MapPOI.is_active == True,
        ).first()

    return robot.min_battery, charging_poi


# ─── 배터리 부족 시 충전소 이동 ───────────────────────────────────────────────

def _navigate_to_charger(robot_id: int, robot_ip: str,
                         charging_poi, entry_poi_names: list[str] | None,
                         db, ws, move_lock: threading.Lock,
                         stop_event: threading.Event) -> bool:
    """배터리 부족 시 충전소까지 이동 후 충전 명령
    경로: entry_poi_names 역순 → 충전소
    반환: True(성공) / False(실패)
    """
    # 1. 충전 경로 구성: entry_poi_names 역순
    route_pois = []
    if entry_poi_names:
        reversed_names = list(reversed(entry_poi_names))
        for name in reversed_names:
            poi = db.query(MapPOI).filter(
                MapPOI.name == name,
                MapPOI.is_active == True,
            ).first()
            if poi:
                route_pois.append(poi)

    # 2. route_coordinates 생성 (경유 POI들 + 충전소 POI)
    coords_parts = []
    for p in route_pois:
        px = p.world_x if p.world_x is not None else p.x
        py = p.world_y if p.world_y is not None else p.y
        coords_parts.extend([str(px), str(py)])

    cx = charging_poi.world_x if charging_poi.world_x is not None else charging_poi.x
    cy = charging_poi.world_y if charging_poi.world_y is not None else charging_poi.y
    c_angle = charging_poi.angle if charging_poi.angle is not None else 0.0
    coords_parts.extend([str(cx), str(cy)])
    route_coords = ",".join(coords_parts) if len(coords_parts) > 2 else ""

    route_desc = " → ".join([p.name for p in route_pois] + [charging_poi.name])
    logger.info(f"[Robot {robot_id}] 배터리 부족 → 충전소 이동: {route_desc}")

    # 3. 상태 업데이트
    with _lock:
        _run_info[robot_id] = {
            "status": "low_battery_charging",
            "message": f"배터리 부족 — 충전소 이동 중 ({route_desc})",
            "error_code": "ROBOT-007",
            "description": "_navigate_to_charger() — 배터리 부족",
        }

    # 4. 이동 명령 전송
    with move_lock:
        ok, move_id, err = send_move(robot_ip, cx, cy, c_angle, route_coords=route_coords)
        if not ok:
            logger.error(f"[Robot {robot_id}] 충전소 이동 명령 실패: {err}")
            with _lock:
                _run_info[robot_id] = {
                    "status": "error",
                    "message": "충전소 이동에 실패했습니다.",
                    "error_code": "ROBOT-005",
                    "description": "_navigate_to_charger() — 충전소 이동 명령 실패",
                }
            return False

        logger.info(f"[Robot {robot_id}] 충전소 이동 Move {move_id} 전송")

        if ws:
            try:
                result, detail = _wait_for_move_ws(ws, move_id, robot_ip, stop_event)
            except (WebSocketException, OSError):
                result, detail = _wait_for_move_http(robot_ip, move_id, stop_event)
        else:
            result, detail = _wait_for_move_http(robot_ip, move_id, stop_event)

    if result != "succeeded":
        logger.error(f"[Robot {robot_id}] 충전소 이동 실패: {result} {detail}")
        with _lock:
            _run_info[robot_id] = {
                "status": "error",
                "message": f"충전소 이동에 실패했습니다. ({detail})",
                "error_code": "ROBOT-005",
                "description": "_navigate_to_charger() — 충전소 이동 실패",
            }
        return False

    # 5. 충전소 도착 → 충전 명령 (charger_name으로 overlay ID 자동 매칭)
    time.sleep(1)
    cname = charging_poi.name if charging_poi else None
    ok, msg = send_charge(robot_ip, charger_name=cname)
    logger.info(f"[Robot {robot_id}] 충전 명령 전송 (charger={cname}): ok={ok}, {msg}")

    with _lock:
        _run_info[robot_id] = {
            "status": "charging",
            "message": "배터리 부족 — 충전 중",
        }

    return ok


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
    ws = None
    move_lock = _get_move_lock(robot_id)
    stop_set = set(stop_names) if stop_names else set()
    graceful_stop = threading.Event()
    with _lock:
        _graceful_stop_events[robot_id] = graceful_stop

    try:
        # DB에서 POI 좌표 조회 (세션 즉시 반환)
        pois = []
        entry_pois = []
        db = SessionLocal()
        try:
            # ── 활성 맵 ID 자동 감지 (중복 POI 이름 방지) ──
            first_poi = db.query(MapPOI).join(RobotMap).filter(
                MapPOI.name == poi_names[0],
                MapPOI.is_active == True,
                RobotMap.is_active == True,
            ).order_by(RobotMap.id.desc()).first()
            if not first_poi:
                logger.error(f"[Robot {robot_id}] POI '{poi_names[0]}' 을 찾을 수 없습니다")
                with _lock:
                    _run_info[robot_id] = {"status": "error", "message": f"POI '{poi_names[0]}' 없음"}
                return
            target_map_id = first_poi.map_id
            logger.info(f"[Robot {robot_id}] 활성 맵 ID: {target_map_id}")

            for name in poi_names:
                poi = db.query(MapPOI).filter(
                    MapPOI.name == name,
                    MapPOI.is_active == True,
                    MapPOI.map_id == target_map_id,
                ).first()
                if not poi:
                    logger.error(f"[Robot {robot_id}] POI '{name}' 을 찾을 수 없습니다 (map_id={target_map_id})")
                    with _lock:
                        _run_info[robot_id] = {"status": "error", "message": f"POI '{name}' 없음"}
                    return
                db.expunge(poi)
                pois.append(poi)

            if entry_poi_names:
                for name in entry_poi_names:
                    poi = db.query(MapPOI).filter(
                        MapPOI.name == name,
                        MapPOI.is_active == True,
                        MapPOI.map_id == target_map_id,
                    ).first()
                    if not poi:
                        logger.error(f"[Robot {robot_id}] 진입 POI '{name}' 을 찾을 수 없습니다 (map_id={target_map_id})")
                        with _lock:
                            _run_info[robot_id] = {"status": "error", "message": f"진입 POI '{name}' 없음"}
                        return
                    db.expunge(poi)
                    entry_pois.append(poi)
        finally:
            db.close()  # POI 조회 완료 → DB 세션 즉시 반환

        # WebSocket 연결 시도
        try:
            ws = _create_planning_ws(robot_ip)
        except Exception as e:
            logger.warning(f"[Robot {robot_id}] WebSocket 연결 실패 — HTTP 폴백 사용: {e}")

        # ── 진입 경로 처리 (충전소 → 작업구역, 충전 상태일 때만 1회) ──
        if entry_pois and _is_charging(robot_ip):

            # 진입 경로 → CURPOS1(pois[0])까지 이어서 이동 (ENTERPOS3에서 멈추지 않음)
            first_loop_poi = pois[0]
            logger.info(f"[Robot {robot_id}] 진입 경로 시작: "
                        f"{'→'.join(p.name for p in entry_pois)}→{first_loop_poi.name}")

            # route_coordinates: 진입 POI들 + CURPOS1 좌표를 이어서 한 번에 이동
            entry_target = first_loop_poi
            entry_coords_parts = []
            for ep in entry_pois:
                ex = ep.world_x if ep.world_x is not None else ep.x
                ey = ep.world_y if ep.world_y is not None else ep.y
                entry_coords_parts.extend([str(ex), str(ey)])

            etx = entry_target.world_x if entry_target.world_x is not None else entry_target.x
            ety = entry_target.world_y if entry_target.world_y is not None else entry_target.y
            et_angle = entry_target.angle if entry_target.angle is not None else 0.0
            entry_coords_parts.extend([str(etx), str(ety)])
            entry_route_coords = ",".join(entry_coords_parts) if len(entry_coords_parts) > 2 else ""

            with _lock:
                _run_info[robot_id] = {
                    "status": "moving_to_start",
                    "current_poi": entry_target.name,
                    "message": "작업 시작 위치로 진입 중",
                }

            with move_lock:
                ok, move_id, err = send_move(
                    robot_ip, etx, ety, et_angle, route_coords=entry_route_coords)
                if not ok:
                    logger.error(f"[Robot {robot_id}] 진입 경로 이동 명령 실패: {err}")
                    with _lock:
                        _run_info[robot_id] = {"status": "error", "message": "진입 경로 이동 명령에 실패했습니다.", "error_code": "TASK-007", "description": "_task_runner() — 진입 경로 이동 실패"}
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
                    _run_info[robot_id] = {"status": "error", "message": f"진입 경로 이동에 실패했습니다. ({detail})", "error_code": "TASK-007", "description": "_task_runner() — 진입 경로 이동 실패"}
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
                _run_info[robot_id] = {"status": "error", "message": "작업 포인트를 찾지 못했습니다.", "error_code": "TASK-004", "description": "_task_runner() — 정지 포인트 없음"}
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

            # ── 배터리 체크 (2회차 루프부터) ──
            # 배터리 부족 시: CURPOS1 복귀 → ENTERPOS 역순 → 충전소
            if loop > 1:
                battery_pct = _get_battery_percentage(robot_ip)
                if battery_pct is not None:
                    min_bat, charging_poi = _get_charging_config(db, robot_id)
                    logger.info(f"[Robot {robot_id}] 배터리: {battery_pct:.1f}% (최소: {min_bat}%)")

                    if battery_pct <= min_bat:
                        logger.warning(f"[Robot {robot_id}] 배터리 부족! "
                                       f"{battery_pct:.1f}% <= {min_bat}%")

                        if charging_poi:
                            with _lock:
                                _charging_robots.add(robot_id)

                            # 1단계: CURPOS1(pois[0])으로 먼저 복귀
                            home_poi = pois[0]
                            logger.info(f"[Robot {robot_id}] 배터리 부족 — {home_poi.name}으로 복귀 중")

                            home_coords_parts = []
                            for wp in trailing_waypoints:
                                wx = wp.world_x if wp.world_x is not None else wp.x
                                wy = wp.world_y if wp.world_y is not None else wp.y
                                home_coords_parts.extend([str(wx), str(wy)])
                            hx = home_poi.world_x if home_poi.world_x is not None else home_poi.x
                            hy = home_poi.world_y if home_poi.world_y is not None else home_poi.y
                            h_angle = home_poi.angle if home_poi.angle is not None else 0.0
                            home_coords_parts.extend([str(hx), str(hy)])
                            home_route = ",".join(home_coords_parts) if len(home_coords_parts) > 2 else ""

                            with _lock:
                                _run_info[robot_id] = {
                                    "status": "low_battery_charging",
                                    "loop": loop,
                                    "current_poi": home_poi.name,
                                    "message": f"배터리 부족 — {home_poi.name}으로 복귀 중",
                                    "error_code": "ROBOT-007",
                                    "description": "_task_runner() — 배터리 부족",
                                }

                            home_ok = False
                            with move_lock:
                                ok, move_id, err = send_move(robot_ip, hx, hy, h_angle, route_coords=home_route)
                                if ok:
                                    if ws:
                                        try:
                                            h_result, h_detail = _wait_for_move_ws(ws, move_id, robot_ip, stop_event, robot_id=robot_id)
                                        except (WebSocketException, OSError):
                                            h_result, h_detail = _wait_for_move_http(robot_ip, move_id, stop_event)
                                    else:
                                        h_result, h_detail = _wait_for_move_http(robot_ip, move_id, stop_event)
                                    home_ok = (h_result == "succeeded")
                                    logger.info(f"[Robot {robot_id}] {home_poi.name} 복귀 결과: {h_result}")
                                else:
                                    logger.error(f"[Robot {robot_id}] {home_poi.name} 복귀 이동 실패: {err}")

                            if not home_ok:
                                logger.error(f"[Robot {robot_id}] {home_poi.name} 복귀 실패 — 현재 위치에서 충전소 이동 시도")
                                with _lock:
                                    _run_info[robot_id] = {
                                        "status": "low_battery_charging",
                                        "loop": loop,
                                        "current_poi": charging_poi.name,
                                        "message": f"{home_poi.name} 복귀 실패 — 현재 위치에서 충전소 이동 시도",
                                        "error_code": "ROBOT-007",
                                        "description": "_task_runner() — 배터리 부족",
                                    }

                            # 2단계: ENTERPOS 역순 → 충전소 이동
                            _navigate_to_charger(
                                robot_id, robot_ip, charging_poi,
                                entry_poi_names, db, ws, move_lock, stop_event
                            )

                            # 모든 활성 로봇이 충전소로 갔는지 확인
                            with _lock:
                                active_robots = set(_stop_events.keys())
                                all_charging = active_robots.issubset(_charging_robots)

                            if all_charging and len(active_robots) > 0:
                                logger.info(f"모든 로봇({active_robots})이 충전소 이동 → 전체 작업 종료")
                                with _lock:
                                    for rid in active_robots:
                                        ev = _stop_events.get(rid)
                                        if ev:
                                            ev.set()

                            with _lock:
                                _run_info[robot_id] = {
                                    "status": "charging",
                                    "message": "배터리 부족 — 충전 중 (작업 종료)",
                                    "error_code": "ROBOT-008",
                                    "description": "_task_runner() — 배터리 부족으로 충전 진입",
                                }
                            return
                        else:
                            logger.warning(f"[Robot {robot_id}] charging_id 미설정 — 충전소 이동 불가, 계속 작업")
                else:
                    logger.warning(f"[Robot {robot_id}] 배터리 정보 조회 실패 — 스킵")

            for seg_idx, seg in enumerate(segments):
                if stop_event.is_set():
                    break
                # 그레이스풀 정지: 현재 구간 이동 중에는 중단하지 않음 (확인 대기 중이면 스킵)

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
                                _run_info[robot_id] = {"status": "error", "message": "이동 명령에 실패했습니다.", "error_code": "TASK-005", "description": "_task_runner() — 로봇 이동 명령 실패"}
                            return

                        logger.info(f"[Robot {robot_id}] Move {move_id} 전송 완료")

                        # WebSocket 또는 HTTP 폴백으로 이동 완료 대기
                        if ws:
                            try:
                                result, detail = _wait_for_move_ws(
                                    ws, move_id, robot_ip, stop_event, robot_id=robot_id)
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
                            "message": f"이동에 실패했습니다. ({detail})",
                            "error_code": "TASK-005",
                            "description": "_task_runner() — 로봇 이동 명령 실패",
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

                    # 확인 또는 즉시정지 신호 대기 (그레이스풀 정지 중에도 확인은 받음)
                    while not confirm_event.is_set():
                        if stop_event.is_set():
                            break
                        confirm_event.wait(timeout=1.0)

                    with _lock:
                        _confirm_events.pop(robot_id, None)

                    if stop_event.is_set():
                        break

                    logger.info(f"[Robot {robot_id}] 작업 포인트 '{target.name}' 확인 완료 — 다음 구간 진행")

            else:
                # for 루프가 break 없이 정상 완료 (모든 구간 수행 완료)
                if graceful_stop.is_set():
                    # ── CURPOS1으로 귀환 후 정지 ──
                    home_poi = pois[0]  # CURPOS1
                    logger.info(f"[Robot {robot_id}] 그레이스풀 정지 — {home_poi.name}으로 귀환 중")

                    # trailing_waypoints + home_poi 경로 생성
                    home_coords_parts = []
                    for wp in trailing_waypoints:
                        wx = wp.world_x if wp.world_x is not None else wp.x
                        wy = wp.world_y if wp.world_y is not None else wp.y
                        home_coords_parts.extend([str(wx), str(wy)])
                    hx = home_poi.world_x if home_poi.world_x is not None else home_poi.x
                    hy = home_poi.world_y if home_poi.world_y is not None else home_poi.y
                    h_angle = home_poi.angle if home_poi.angle is not None else 0.0
                    home_coords_parts.extend([str(hx), str(hy)])
                    home_route = ",".join(home_coords_parts) if len(home_coords_parts) > 2 else ""

                    with _lock:
                        _run_info[robot_id] = {
                            "status": "moving_to_start",
                            "loop": loop,
                            "current_poi": home_poi.name,
                            "message": "작업 시작 위치로 복귀 중",
                        }

                    with move_lock:
                        ok, move_id, err = send_move(robot_ip, hx, hy, h_angle, route_coords=home_route)
                        if ok:
                            if ws:
                                try:
                                    result, detail = _wait_for_move_ws(ws, move_id, robot_ip, stop_event)
                                except Exception:
                                    result, detail = _wait_for_move_http(robot_ip, move_id, stop_event)
                            else:
                                result, detail = _wait_for_move_http(robot_ip, move_id, stop_event)
                            logger.info(f"[Robot {robot_id}] 귀환 결과: {result}")

                    logger.info(f"[Robot {robot_id}] {home_poi.name} 도착 — 정지")
                    with _lock:
                        _run_info[robot_id] = {"status": "stopped", "loop": loop}
                    return
                continue  # 다음 루프 반복

        # stop_event로 중단됨
        logger.info(f"[Robot {robot_id}] 즉시 정지 — {loop}회차 중단")
        with _lock:
            _run_info[robot_id] = {"status": "stopped", "loop": loop}

    except Exception as e:
        logger.exception(f"[Robot {robot_id}] 예외: {e}")
        with _lock:
            _run_info[robot_id] = {"status": "error", "message": "작업 실행 중 오류가 발생했습니다.", "error_code": "TASK-013", "description": "_task_runner() — 예외 catch"}
    finally:
        if ws:
            try:
                ws.close()
            except Exception:
                pass
        # DB 세션은 POI 조회 직후 이미 닫힘
        with _lock:
            _stop_events.pop(robot_id, None)
            _confirm_events.pop(robot_id, None)
            _graceful_stop_events.pop(robot_id, None)
            _charging_robots.discard(robot_id)
            _stuck_states.pop(robot_id, None)
        logger.info(f"[Robot {robot_id}] 스레드 종료")


# ─── 공개 인터페이스 ────────────────────────────────────────────────────────────

def start_loop(robot_id: int, robot_ip: str, poi_names: list[str],
               stop_names: list[str] | None = None,
               entry_poi_names: list[str] | None = None) -> tuple[bool, str, str | None]:
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
                return False, "이미 실행 중입니다.", "TASK-001"
        if not poi_names:
            return False, "POI 목록이 비어 있습니다.", "TASK-002"

        stop_event = threading.Event()
        _stop_events[robot_id] = stop_event
        _run_info[robot_id] = {"status": "starting", "poi_list": poi_names}
        _charging_robots.discard(robot_id)

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
    return True, "무한반복 작업이 시작되었습니다.", None


def confirm_loop(robot_id: int) -> tuple[bool, str, str | None]:
    """작업 포인트 확인 → 다음 구간 진행 (스레드 안전)
    로봇 태블릿에서 호출하여 작업 포인트 대기 해제
    """
    with _lock:
        event = _confirm_events.get(robot_id)
        if not event:
            info = _run_info.get(robot_id, {})
            if info.get("status") != "waiting_confirmation":
                return False, "확인 대기 중인 작업이 없습니다.", "TASK-010"
            return False, "확인 이벤트를 찾지 못했습니다.", "TASK-010"
    event.set()
    logger.info(f"[Robot {robot_id}] 태블릿 확인 신호 수신")
    return True, "확인 완료 — 다음 구간으로 진행합니다.", None


def stop_loop(robot_id: int, robot_ip: str = "") -> tuple[bool, str, str | None]:
    """실행 중인 무한반복 → CURPOS1 도착 후 정지 (그레이스풀 정지)"""
    with _lock:
        event = _stop_events.get(robot_id)
        if not event:
            info = _run_info.get(robot_id, {})
            if info.get("status") in ("error", "stopped"):
                _run_info.pop(robot_id, None)
            if robot_ip:
                cancel_current_move(robot_ip)
            return False, "실행 중인 작업이 없습니다.", "TASK-008"
        graceful = _graceful_stop_events.get(robot_id)
    if graceful:
        graceful.set()
        logger.info(f"[Robot {robot_id}] 그레이스풀 정지 요청 — CURPOS1 도착 후 종료")
        return True, "현재 루프 완료 후 CURPOS1에서 정지합니다.", None
    # graceful event가 없으면 즉시 정지 (폴백)
    event.set()
    if robot_ip:
        cancel_current_move(robot_ip)
    logger.info(f"[Robot {robot_id}] 즉시 정지 요청")
    return True, "정지 요청을 전송했습니다.", None


def get_loop_status(robot_id: int) -> dict:
    """실행 상태 조회 (스레드 안전)"""
    with _lock:
        running = robot_id in _stop_events
        info = _run_info.get(robot_id)
        stuck = _stuck_states.get(robot_id, False)
    result = {}
    if running:
        result = info.copy() if info else {"status": "running"}
    elif info:
        result = info.copy()
    else:
        result = {"status": "idle"}
    result["stuck"] = stuck
    return result


def is_running(robot_id: int) -> bool:
    with _lock:
        return robot_id in _stop_events
