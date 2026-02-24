import json
import threading
import time
from typing import Any, Optional

import requests
from websocket import WebSocketException, create_connection


PORT = 8090
HTTP_TIMEOUT = 15
WS_TIMEOUT = 15

MAP_WS_TOPICS = [
    "/map",
    "/maps/5cm/1hz",
    "/tracked_pose",
    "/trajectory",
    "/scan_matched_points2",
]


# ── HTTP helpers ──────────────────────────────────────────────

def _request(
    ip: str,
    secret: str,
    method: str,
    path: str,
    json_data: Any = None,
    timeout: int = HTTP_TIMEOUT,
) -> dict:
    url = f"http://{ip}:{PORT}{path}"
    headers = {"Secret": secret}
    res = requests.request(
        method,
        url,
        headers=headers,
        json=json_data,
        timeout=timeout,
    )
    if not res.ok:
        error_body = ""
        try:
            error_body = res.text[:500]
        except Exception:
            pass
        print(f"[robot_api] {method} {path} → {res.status_code}: {error_body}")
        res.raise_for_status()
    if res.status_code == 204 or not res.content:
        return {}
    return res.json()


def _get(ip: str, secret: str, path: str) -> dict:
    return _request(ip, secret, "GET", path)


def _post(ip: str, secret: str, path: str, data: Any = None) -> dict:
    return _request(ip, secret, "POST", path, json_data=data)


def _put(ip: str, secret: str, path: str, data: Any = None) -> dict:
    return _request(ip, secret, "PUT", path, json_data=data)


def _delete(ip: str, secret: str, path: str) -> dict:
    return _request(ip, secret, "DELETE", path)


def _patch(ip: str, secret: str, path: str, data: Any = None) -> dict:
    return _request(ip, secret, "PATCH", path, json_data=data)


# ── /maps ─────────────────────────────────────────────────────

def get_maps(ip: str, secret: str) -> dict:
    return _get(ip, secret, "/maps")


def get_map(ip: str, secret: str, map_name: str) -> dict:
    return _get(ip, secret, f"/maps/{map_name}")


def create_map(ip: str, secret: str, data: dict) -> dict:
    return _post(ip, secret, "/maps/", data)


def update_map(ip: str, secret: str, map_name: str, data: dict) -> dict:
    return _put(ip, secret, f"/maps/{map_name}", data)


def delete_map(ip: str, secret: str, map_name: str) -> dict:
    return _delete(ip, secret, f"/maps/{map_name}")


def patch_map(ip: str, secret: str, map_name: str, data: dict) -> dict:
    return _patch(ip, secret, f"/maps/{map_name}", data)


def get_map_by_id(ip: str, secret: str, map_id: int) -> dict:
    """숫자 ID로 로봇 맵 상세 조회 — GET /maps/{id}"""
    return _get(ip, secret, f"/maps/{map_id}")


def delete_map_by_id(ip: str, secret: str, map_id: int) -> dict:
    """숫자 ID로 로봇 맵 삭제 — DELETE /maps/{id}"""
    return _delete(ip, secret, f"/maps/{map_id}")


def patch_map_by_id(ip: str, secret: str, map_id: int, data: dict) -> dict:
    """숫자 ID로 로봇 맵 부분 수정 — PATCH /maps/{id}"""
    return _patch(ip, secret, f"/maps/{map_id}", data)


# ── /chassis ──────────────────────────────────────────────────

def set_chassis_pose(ip: str, secret: str, data: dict) -> dict:
    return _post(ip, secret, "/chassis/pose", data)


def set_current_map(ip: str, secret: str, data: dict) -> dict:
    """현재 지도 설정 — POST /chassis/current-map {map_id: ...}"""
    return _post(ip, secret, "/chassis/current-map", data)


# ── /mappings ─────────────────────────────────────────────────

def get_mappings(ip: str, secret: str) -> dict:
    return _get(ip, secret, "/mappings/")


def get_mapping_by_id(ip: str, secret: str, mapping_id: int) -> dict:
    return _get(ip, secret, f"/mappings/{mapping_id}")


def create_mapping(ip: str, secret: str, data: dict) -> dict:
    return _post(ip, secret, "/mappings/", data)


def update_mapping(ip: str, secret: str, data: dict) -> dict:
    return _put(ip, secret, "/mappings/", data)


def delete_mapping(ip: str, secret: str) -> dict:
    return _delete(ip, secret, "/mappings/")


def patch_mapping(ip: str, secret: str, data: dict) -> dict:
    return _patch(ip, secret, "/mappings/", data)


# ── /mappings/current ─────────────────────────────────────────

def get_current_mapping(ip: str, secret: str) -> dict:
    return _get(ip, secret, "/mappings/current")


def create_current_mapping(ip: str, secret: str, data: dict) -> dict:
    return _post(ip, secret, "/mappings/current", data)


def update_current_mapping(ip: str, secret: str, data: dict) -> dict:
    return _put(ip, secret, "/mappings/current", data)


def delete_current_mapping(ip: str, secret: str) -> dict:
    return _delete(ip, secret, "/mappings/current")


def patch_current_mapping(ip: str, secret: str, data: dict) -> dict:
    return _patch(ip, secret, "/mappings/current", data)


# ── WebSocket relay (robot → queue) ──────────────────────────

class RobotWSRelay:
    """로봇 WebSocket에 연결하여 토픽 데이터를 큐로 전달하는 백그라운드 릴레이."""

    def __init__(self, ip: str, secret: str, topics: Optional[list[str]] = None):
        self.ip = ip
        self.secret = secret
        self.topics = topics or MAP_WS_TOPICS
        self._ws = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._queue: list[str] = []
        self._lock = threading.Lock()
        self._send_queue: list[str] = []
        self._send_lock = threading.Lock()

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._ws is not None:
            try:
                self._ws.close()
            except Exception:
                pass
        if self._thread is not None:
            self._thread.join(timeout=3)

    def send_to_robot(self, message: str):
        with self._send_lock:
            self._send_queue.append(message)

    def poll(self) -> list[str]:
        with self._lock:
            items = self._queue[:]
            self._queue.clear()
        return items

    def _run(self):
        ws_url = f"ws://{self.ip}:{PORT}/ws/v2/topics"
        max_retries = 3

        for attempt in range(max_retries):
            if not self._running:
                return
            try:
                self._ws = create_connection(ws_url, timeout=WS_TIMEOUT)

                for topic in self.topics:
                    self._ws.send(json.dumps({"enable_topic": topic}))

                self._ws.settimeout(0.1)

                while self._running:
                    # 프론트엔드 → 로봇 전달
                    with self._send_lock:
                        pending = self._send_queue[:]
                        self._send_queue.clear()
                    for msg in pending:
                        try:
                            self._ws.send(msg)
                        except Exception:
                            pass

                    # 로봇 → 큐 수집
                    try:
                        raw = self._ws.recv()
                        if raw:
                            with self._lock:
                                self._queue.append(raw)
                    except Exception:
                        pass

                return  # 정상 종료

            except (WebSocketException, OSError, TimeoutError) as exc:
                if self._ws is not None:
                    try:
                        self._ws.close()
                    except Exception:
                        pass
                    self._ws = None

                if attempt < max_retries - 1:
                    time.sleep(2)  # 재시도 전 대기
                    continue

                error_msg = json.dumps({"error": f"robot_ws_connection_failed: {exc}"})
                with self._lock:
                    self._queue.append(error_msg)

            finally:
                if self._ws is not None:
                    try:
                        self._ws.close()
                    except Exception:
                        pass
