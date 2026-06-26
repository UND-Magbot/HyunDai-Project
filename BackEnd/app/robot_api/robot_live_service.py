import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import requests
from websocket import WebSocketException, create_connection


PORT = 8090
HTTP_TIMEOUT = 2
WS_TIMEOUT = 2

# 오프라인 로봇 캐시 — 한번 실패하면 60초간 재시도 안 함
_offline_cache: dict[str, float] = {}  # {ip: 실패 시각}
_OFFLINE_CACHE_TTL = 60.0

# 전역 ThreadPoolExecutor — 매 요청마다 새 executor 생성 시 thread 누수 발생 (2026-04-29 사건)
# /api/robots/live가 초당 여러 번 폴링되어 48분만에 thread 한도(만 단위) 도달
# 16개 worker만 영구적으로 유지하고 재사용
_LIVE_EXECUTOR = ThreadPoolExecutor(max_workers=16, thread_name_prefix="robot-live")

REST_ENDPOINTS = {
    "device_info": "/device/info",
    # "wifi_info": "/device/wifi_info",  # 성능 최적화: 필수 아닌 조회 스킵
}
WS_TOPICS = ["/planning_state", "/detailed_battery_state", "/battery_state"]


def _get(ip: str, secret: str, path: str) -> dict:
    url = f"http://{ip}:{PORT}{path}"
    res = requests.get(url, headers={"Secret": secret}, timeout=HTTP_TIMEOUT)
    res.raise_for_status()
    return res.json()


def _collect_ws_topics(ip: str, topics: list[str], timeout_sec: int = WS_TIMEOUT) -> tuple[dict, str | None]:
    collected: dict = {}
    ws = None
    ws_url = f"ws://{ip}:{PORT}/ws/v2/topics"
    deadline = time.time() + timeout_sec

    try:
        ws = create_connection(ws_url, timeout=HTTP_TIMEOUT)

        for topic in topics:
            ws.send(json.dumps({"enable_topic": topic}))

        while time.time() < deadline:
            raw = ws.recv()
            if not raw:
                continue

            packet = json.loads(raw)
            topic_name = packet.get("topic")
            if topic_name in topics:
                collected[topic_name] = packet
                if "/planning_state" in collected and (
                    "/detailed_battery_state" in collected or "/battery_state" in collected
                ):
                    break

        return collected, None
    except (WebSocketException, OSError, json.JSONDecodeError) as exc:
        return collected, str(exc)
    finally:
        if ws is not None:
            ws.close()


def _to_runstate(planning: dict, battery: dict, online: bool) -> str:
    if not online:
        return "OFFLINE"
    if not planning and not battery:
        return "N/A"

    move_state = str(planning.get("move_state", "")).lower()
    power_supply_status = str(battery.get("power_supply_status", "")).lower()
    action_type = str(planning.get("action_type", "")).lower()
    waiting_for_dest = planning.get("is_waiting_for_dest") is True

    if move_state == "moving":
        return "EXECUTING"

    # 충전 판정: power_supply_status(BMS) + action_type 조합
    # - charging: 명확히 충전 중
    # - discharging/not_charging: 명확히 비충전 (이전 charge 액션 무시)
    # - full: 완충 상태이지만 충전기 연결 여부 불명확 → action_type 보조 판정
    #         (사람이 충전기 분리해도 BMS가 full을 유지하는 케이스 대응)
    is_charge_action = action_type == "charge"

    if power_supply_status == "charging":
        return "CHARGING"

    if power_supply_status in {"discharging", "not_charging"}:
        return "IDLE"

    if power_supply_status == "full":
        # action_type=charge면 여전히 충전기에 도킹 중, 아니면 분리됨
        return "CHARGING" if is_charge_action else "IDLE"

    # power_supply_status 정보 없을 때만 action_type 폴백
    if is_charge_action and move_state in {"idle", "none", "succeeded"}:
        return "CHARGING"

    if move_state in {"idle", "failed", "cancelled", "succeeded"} or waiting_for_dest:
        return "IDLE"

    return "IDLE"

def _to_power(percentage: Any, online: bool) -> str:
    if not online:
        return "-"
    if not isinstance(percentage, (int, float)):
        return "N/A"
    if percentage <= 1:
        percentage = percentage * 100
    return f"{max(0, min(100, int(round(percentage))))}%"


def _to_signal(wifi_info: dict, online: bool) -> str:
    if not online:
        return "N/A"

    ap = wifi_info.get("active_access_point", {}) if isinstance(wifi_info, dict) else {}
    if isinstance(ap.get("strength"), (int, float)):
        return f"{int(round(max(0, min(100, ap['strength']))))}%"
    if isinstance(wifi_info.get("strength"), (int, float)):
        return f"{int(round(max(0, min(100, wifi_info['strength']))))}%"
    return "N/A"


def fetch_robot_live(ip: str, secret: str) -> dict:
    rest_data: dict = {}
    errors: dict = {}
    online = False

    # 오프라인 캐시: 최근 60초 내 실패한 로봇은 즉시 오프라인 반환
    cached_fail = _offline_cache.get(ip)
    if cached_fail and (time.time() - cached_fail) < _OFFLINE_CACHE_TTL:
        return {
            "IP": ip, "SN": "N/A", "ROBOTNAME": "N/A", "MODEL": "N/A",
            "NICKNAME": None, "AXBOT_VERSION": None, "PLATFORM": None,
            "RUNSTATE": "OFFLINE", "ONLINE": "Offline", "SIGNAL": "N/A",
            "POWER(%)": "-", "errors": {"cached": "오프라인 캐시"},
        }

    for key, path in REST_ENDPOINTS.items():
        try:
            rest_data[key] = _get(ip, secret, path)
            if key == "device_info":
                online = True
        except requests.RequestException as exc:
            errors[key] = str(exc)

    # HTTP 실패 → 오프라인 캐시 등록, WS 스킵
    if not online:
        _offline_cache[ip] = time.time()
        return {
            "IP": ip, "SN": "N/A", "ROBOTNAME": "N/A", "MODEL": "N/A",
            "NICKNAME": None, "AXBOT_VERSION": None, "PLATFORM": None,
            "RUNSTATE": "OFFLINE", "ONLINE": "Offline", "SIGNAL": "N/A",
            "POWER(%)": "-", "errors": errors,
        }

    # 온라인이면 캐시 제거
    _offline_cache.pop(ip, None)

    ws_data, ws_error = _collect_ws_topics(ip, WS_TOPICS)
    if ws_error:
        errors["ws_topics"] = ws_error

    device_info = rest_data.get("device_info", {}).get("device", {})
    planning = ws_data.get("/planning_state", {})
    battery = ws_data.get("/detailed_battery_state", {}) or ws_data.get("/battery_state", {})
    wifi_info = rest_data.get("wifi_info", {})

    return {
        "IP": ip,
        "SN": device_info.get("sn", "N/A"),
        "ROBOTNAME": device_info.get("name", "N/A"),
        "MODEL": device_info.get("model", "N/A"),
        "NICKNAME": device_info.get("nickname"),
        "AXBOT_VERSION": rest_data.get("device_info", {}).get("axbot_version"),
        "PLATFORM": device_info.get("platform"),
        "RUNSTATE": _to_runstate(planning, battery, online),
        "ONLINE": "Online" if online else "Offline",
        "SIGNAL": _to_signal(wifi_info, online),
        "POWER(%)": _to_power(battery.get("percentage"), online),
        "errors": errors,
    }


def fetch_all_robots_live(robots: list[dict]) -> dict:
    if not robots:
        return {"total": 0, "items": []}

    items: list[dict] = []

    # 전역 _LIVE_EXECUTOR 재사용 — 매번 새 ThreadPoolExecutor 생성 시 thread 누수 발생
    future_map = {
        _LIVE_EXECUTOR.submit(fetch_robot_live, robot["ip"], robot["secret"]): robot
        for robot in robots
    }

    # as_completed에 timeout 추가 — 죽은 로봇 끼면 영원히 안 풀리던 문제 방지
    # HTTP_TIMEOUT(2) + WS_TIMEOUT(2) × N + 마진 → 15초면 충분
    AS_COMPLETED_TIMEOUT = 15.0
    completed_futures: set = set()

    def _offline_item(robot: dict, reason: str) -> dict:
        return {
            "IP": robot.get("ip", "N/A"),
            "SN": "N/A",
            "ROBOTNAME": "N/A",
            "MODEL": "N/A",
            "NICKNAME": None,
            "AXBOT_VERSION": None,
            "PLATFORM": None,
            "RUNSTATE": "OFFLINE",
            "ONLINE": "Offline",
            "SIGNAL": "N/A",
            "POWER(%)": "-",
            "errors": {"fetch_robot_live": reason},
        }

    try:
        for future in as_completed(future_map, timeout=AS_COMPLETED_TIMEOUT):
            completed_futures.add(future)
            robot = future_map[future]
            try:
                items.append(future.result(timeout=1.0))
            except Exception as exc:
                items.append(_offline_item(robot, str(exc)))
    except TimeoutError:
        # as_completed 타임아웃 — 미완료 future는 OFFLINE 처리하고 다음 폴링에 맡김
        for fut, robot in future_map.items():
            if fut not in completed_futures:
                fut.cancel()
                items.append(_offline_item(robot, "as_completed timeout"))

    items.sort(key=lambda x: str(x.get("IP", "")))
    return {"total": len(items), "items": items}
