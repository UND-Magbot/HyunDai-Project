import json
import time
import requests
from websocket import create_connection, WebSocketException

PORT = 8090
TIMEOUT = 3
WS_TIMEOUT = 5
AUTO_SWITCH_TO_STATION = False
TARGET_WIFI_SSID = "und_sw5G"
TARGET_WIFI_PSK = "unde9876"
TARGET_ROUTE_MODE = "wlan0_first"
ROBOTS = [
    {"ip": "192.168.0.30", "secret": "19a11878aaab420fba94577ce3620dce"},
    {"ip": "192.168.0.31", "secret": "19a11878aaab420fba94577ce3620dce"},
    {"ip": "192.168.0.32", "secret": "19a11878aaab420fba94577ce3620dce"},
]

ENDPOINTS = {
    "device_info": "/device/info",
    "wifi_info": "/device/wifi_info",
    "available_wifis": "/device/available_wifis",
}
WS_TOPICS = ["/planning_state", "/detailed_battery_state", "/battery_state"]


def _get(robot_ip: str, secret: str, path: str) -> dict:
    url = f"http://{robot_ip}:{PORT}{path}"
    headers = {"Secret": secret}
    res = requests.get(url, headers=headers, timeout=TIMEOUT)
    res.raise_for_status()
    return res.json()


def _post(robot_ip: str, secret: str, path: str, payload: dict) -> dict:
    url = f"http://{robot_ip}:{PORT}{path}"
    headers = {"Secret": secret, "Content-Type": "application/json"}
    res = requests.post(url, headers=headers, json=payload, timeout=TIMEOUT)
    res.raise_for_status()
    if res.text:
        return res.json()
    return {"ok": True}


def configure_station_wifi(robot_ip: str, secret: str) -> dict:
    payload = {
        "mode": "station",
        "ssid": TARGET_WIFI_SSID,
        "psk": TARGET_WIFI_PSK,
        "route_mode": TARGET_ROUTE_MODE,
    }
    return _post(robot_ip, secret, "/services/setup_wifi", payload)


def _collect_ws_topics(robot_ip: str, topics: list[str], timeout_sec: int) -> tuple[dict, str | None]:
    collected: dict = {}
    ws = None
    ws_url = f"ws://{robot_ip}:{PORT}/ws/v2/topics"
    deadline = time.time() + timeout_sec

    try:
        ws = create_connection(ws_url, timeout=TIMEOUT)

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

    # 충전 판정 — BMS + action_type 조합 (full 상태 오판 방지)
    is_charge_action = action_type == "charge"

    if power_supply_status == "charging":
        return "CHARGING"
    if power_supply_status in {"discharging", "not_charging"}:
        return "IDLE"
    if power_supply_status == "full":
        return "CHARGING" if is_charge_action else "IDLE"

    # power_supply_status 정보 없을 때만 action_type 폴백
    if is_charge_action and move_state in {"idle", "none", "succeeded"}:
        return "CHARGING"

    if move_state in {"idle", "failed", "cancelled", "succeeded"} or waiting_for_dest:
        return "IDLE"

    return "IDLE"


def _to_power(percentage_value, online: bool) -> str:
    if not online:
        return "-"
    if not isinstance(percentage_value, (int, float)):
        return "N/A"
    if percentage_value <= 1:
        percentage_value = percentage_value * 100
    percentage_value = max(0, min(100, int(round(percentage_value))))
    return f"{percentage_value}%"


def _normalize_wifi_list(payload) -> list[dict]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        if isinstance(payload.get("wifis"), list):
            return [x for x in payload["wifis"] if isinstance(x, dict)]
        if isinstance(payload.get("list"), list):
            return [x for x in payload["list"] if isinstance(x, dict)]
    return []


def _to_signal(wifi_info: dict, available_wifis, online: bool) -> str:
    if not online:
        return "N/A"

    ssid = str(wifi_info.get("ssid", "")).strip()
    wifi_list = _normalize_wifi_list(available_wifis)

    for wifi in wifi_list:
        if str(wifi.get("ssid", "")).strip() != ssid:
            continue
        rssi = wifi.get("rssi")
        if rssi is None:
            rssi = wifi.get("signal")
        if rssi is None:
            rssi = wifi.get("signal_dbm")
        if isinstance(rssi, (int, float)):
            return f"{int(round(rssi))} dBm"

    # Fallback: use currently active AP info from wifi_info
    ap = wifi_info.get("active_access_point", {}) if isinstance(wifi_info, dict) else {}
    for key in ("rssi", "signal_dbm"):
        value = ap.get(key)
        if isinstance(value, (int, float)):
            return f"{int(round(value))} dBm"
    strength = ap.get("strength")
    if isinstance(strength, (int, float)):
        return f"{int(round(max(0, min(100, strength))))}%"

    return "N/A"


def fetch_dashboard_required_data(robot_ip: str, secret: str) -> dict:
    data: dict = {}
    errors = {}
    online = False

    if AUTO_SWITCH_TO_STATION:
        try:
            _ = configure_station_wifi(robot_ip, secret)
        except requests.RequestException as exc:
            errors["setup_wifi"] = str(exc)

    for key, path in ENDPOINTS.items():
        try:
            data[key] = _get(robot_ip, secret, path)
            if key == "device_info":
                online = True
        except requests.RequestException as exc:
            errors[key] = str(exc)

    ws_data, ws_error = _collect_ws_topics(robot_ip, WS_TOPICS, timeout_sec=WS_TIMEOUT)
    if ws_error:
        errors["ws_topics"] = ws_error

    device_info = data.get("device_info", {}).get("device", {})
    planning = ws_data.get("/planning_state", {})
    battery = ws_data.get("/detailed_battery_state", {}) or ws_data.get("/battery_state", {})
    wifi_info = data.get("wifi_info", {})
    available_wifis = data.get("available_wifis", [])

    return {
        "IP": robot_ip,
        "SN": device_info.get("sn", "N/A"),
        "ROBOTNAME": device_info.get("name", "N/A"),
        "MODEL": device_info.get("model", "N/A"),
        "RUNSTATE": _to_runstate(planning, battery, online),
        "ONLINE": "Online" if online else "Offline",
        "SIGNAL": _to_signal(wifi_info, available_wifis, online),
        "POWER(%)": _to_power(battery.get("percentage"), online),
        "errors": errors,
    }


if __name__ == "__main__":
    items = [fetch_dashboard_required_data(r["ip"], r["secret"]) for r in ROBOTS]
    payload = {"total": len(items), "items": items}
    print(json.dumps(payload, indent=2, ensure_ascii=False))
