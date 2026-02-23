import asyncio
import uuid
from pathlib import Path
from typing import Any, Optional

import requests as http_requests
from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

STATIC_MAPS_DIR = Path(__file__).resolve().parent.parent.parent / "static" / "maps"
STATIC_MAPS_DIR.mkdir(parents=True, exist_ok=True)

from app.database import get_db
from app.models.robot import Robot
from app.routers.robot import ROBOTS
from app.crud.map import (
    get_businesses,
    create_business,
    delete_business,
    get_areas,
    create_area,
    delete_area,
    save_robot_map,
    get_maps_by_area,
    get_map_by_id,
    delete_map as crud_delete_map,
    save_map_elements,
    get_map_elements,
)
from app.robot_api.robot_map_service import (
    RobotWSRelay,
    get_maps,
    get_map,
    create_map,
    update_map,
    delete_map,
    patch_map,
    get_mappings,
    get_mapping_by_id,
    create_mapping,
    update_mapping,
    delete_mapping,
    patch_mapping,
    get_current_mapping,
    create_current_mapping,
    update_current_mapping,
    delete_current_mapping,
    patch_current_mapping,
    set_chassis_pose,
)

router = APIRouter(prefix="/api/map", tags=["맵 관리"])


# ── helper ────────────────────────────────────────────────────

def _find_secret(robot_ip: str) -> str:
    for r in ROBOTS:
        if r["ip"] == robot_ip:
            return r["secret"]
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"등록된 로봇을 찾을 수 없습니다: {robot_ip}",
    )


def _proxy(func, *args, **kwargs) -> Any:
    try:
        return func(*args, **kwargs)
    except HTTPException:
        raise
    except http_requests.exceptions.HTTPError as exc:
        # 로봇이 4xx/5xx 응답한 경우
        resp_text = ""
        if exc.response is not None:
            resp_text = exc.response.text[:500]
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"로봇 API 오류 ({exc.response.status_code if exc.response else '?'}): {resp_text or exc}",
        )
    except Exception as exc:
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"로봇 API 호출 실패: {type(exc).__name__}: {exc}",
        )


# ── 로봇 목록 / 연결 확인 ─────────────────────────────────────

@router.get("/robots")
def api_get_robots_for_map(db: Session = Depends(get_db)):
    """맵 편집용 로봇 목록 (DB 내 활성 로봇의 SN·이름·IP 반환)"""
    robots = db.query(Robot).filter(Robot.is_active == True).all()
    return {
        "total": len(robots),
        "items": [
            {
                "sn": r.serial_number,
                "name": r.name,
                "ip_address": r.ip_address,
            }
            for r in robots
        ],
    }


@router.post("/connect/{sn}")
def api_connect_robot(sn: str, db: Session = Depends(get_db)):
    """로봇 연결 확인 — SN으로 IP 조회 후 GET /device/info 호출.
    성공 시 로봇 정보 반환, 실패 시 503."""
    robot = (
        db.query(Robot)
        .filter(Robot.serial_number == sn, Robot.is_active == True)
        .first()
    )
    if not robot:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"로봇을 찾을 수 없습니다: {sn}",
        )
    if not robot.ip_address:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"로봇 IP 주소가 등록되어 있지 않습니다: {sn}",
        )

    try:
        url = f"http://{robot.ip_address}:8090/device/info"
        secret = None
        for r in ROBOTS:
            if r["ip"] == robot.ip_address:
                secret = r["secret"]
                break
        headers = {"Secret": secret} if secret else {}
        res = http_requests.get(url, headers=headers, timeout=10)
        res.raise_for_status()
        device_info = res.json()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"로봇에 연결할 수 없습니다: {exc}",
        )

    return {
        "connected": True,
        "sn": robot.serial_number,
        "name": robot.name,
        "ip_address": robot.ip_address,
        "device_info": device_info,
    }


# ── Business (사업장) CRUD ────────────────────────────────────

@router.get("/businesses")
def api_get_businesses(db: Session = Depends(get_db)):
    """사업장 목록 조회 (드롭다운용)"""
    items = get_businesses(db)
    return {"total": len(items), "items": items}


@router.post("/businesses", status_code=201)
def api_create_business(body: dict, db: Session = Depends(get_db)):
    """사업장 생성"""
    name = body.get("name", "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="사업장 이름은 필수입니다.")
    return create_business(db, name)


@router.delete("/businesses/{business_id}")
def api_delete_business(business_id: int, db: Session = Depends(get_db)):
    """사업장 비활성화"""
    return delete_business(db, business_id)


# ── Area (영역) CRUD ──────────────────────────────────────────

@router.get("/businesses/{business_id}/areas")
def api_get_areas(business_id: int, db: Session = Depends(get_db)):
    """해당 사업장의 영역 목록 조회 (드롭다운용)"""
    items = get_areas(db, business_id)
    return {"total": len(items), "items": items}


@router.post("/areas", status_code=201)
def api_create_area(body: dict, db: Session = Depends(get_db)):
    """영역 생성"""
    business_id = body.get("business_id")
    name = body.get("name", "").strip()
    if not business_id:
        raise HTTPException(status_code=400, detail="business_id는 필수입니다.")
    if not name:
        raise HTTPException(status_code=400, detail="영역 이름은 필수입니다.")
    return create_area(db, business_id, name)


@router.delete("/areas/{area_id}")
def api_delete_area(area_id: int, db: Session = Depends(get_db)):
    """영역 비활성화"""
    return delete_area(db, area_id)


# ── 매핑 결과 저장 / 조회 ─────────────────────────────────────

def _download_robot_image(url: str, prefix: str = "map") -> str | None:
    """로봇 이미지를 다운로드하여 로컬에 저장하고, 서버 경로를 반환."""
    if not url:
        return None
    try:
        res = http_requests.get(url, timeout=15)
        res.raise_for_status()
        # 확장자 추출
        content_type = res.headers.get("Content-Type", "")
        ext = ".png"
        if "jpeg" in content_type or "jpg" in content_type:
            ext = ".jpg"
        filename = f"{prefix}_{uuid.uuid4().hex[:12]}{ext}"
        filepath = STATIC_MAPS_DIR / filename
        filepath.write_bytes(res.content)
        return f"/static/maps/{filename}"
    except Exception:
        return None


@router.post("/maps/save", status_code=201)
def api_save_map(body: dict, db: Session = Depends(get_db)):
    """매핑 종료 후 결과를 DB에 저장.
    이미지를 로봇에서 다운로드하여 로컬 서버에 저장한 뒤 경로를 DB에 기록."""
    # 로봇 URL → 로컬 서버 파일로 다운로드
    if body.get("image_url"):
        local_path = _download_robot_image(body["image_url"], "map_img")
        if local_path:
            body["image_url"] = local_path

    if body.get("thumbnail_url"):
        local_path = _download_robot_image(body["thumbnail_url"], "map_thumb")
        if local_path:
            body["thumbnail_url"] = local_path

    return save_robot_map(db, body)


@router.get("/areas/{area_id}/maps")
def api_get_maps_by_area(area_id: int, db: Session = Depends(get_db)):
    """해당 영역의 저장된 맵 목록 조회 (드롭다운용)"""
    items = get_maps_by_area(db, area_id)
    return {"total": len(items), "items": items}


@router.get("/maps/{map_id}")
def api_get_map_detail(map_id: int, db: Session = Depends(get_db)):
    """맵 단건 조회"""
    return get_map_by_id(db, map_id)


@router.delete("/maps/{map_id}")
def api_delete_saved_map(map_id: int, db: Session = Depends(get_db)):
    """맵 비활성화"""
    return crud_delete_map(db, map_id)


# ── 맵 요소 (POI·라인) 저장 / 조회 ──────────────────────────

@router.put("/maps/{map_id}/elements")
def api_save_map_elements(map_id: int, body: dict, db: Session = Depends(get_db)):
    """맵의 POI·라인을 전체 교체 방식으로 저장"""
    return save_map_elements(db, map_id, body)


@router.get("/maps/{map_id}/elements")
def api_get_map_elements(map_id: int, db: Session = Depends(get_db)):
    """맵에 저장된 POI·라인 조회"""
    return get_map_elements(db, map_id)


# ── 이미지 프록시 ─────────────────────────────────────────────

@router.get("/proxy-image")
def api_proxy_image(url: str = Query(..., description="로봇 이미지 URL")):
    """로봇의 이미지를 프록시하여 CORS 문제 없이 프론트엔드에 전달."""
    try:
        res = http_requests.get(url, timeout=10)
        res.raise_for_status()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"이미지를 가져올 수 없습니다: {exc}")
    content_type = res.headers.get("Content-Type", "image/png")
    return Response(content=res.content, media_type=content_type)


# ── 로봇 프록시: /maps ───────────────────────────────────────

@router.get("/{robot_ip}/maps")
def api_get_robot_maps(robot_ip: str):
    """로봇 맵 목록 조회 (로봇 직접 통신)"""
    secret = _find_secret(robot_ip)
    return _proxy(get_maps, robot_ip, secret)


@router.get("/{robot_ip}/maps/{map_name}")
def api_get_robot_map(robot_ip: str, map_name: str):
    """로봇 맵 상세 조회"""
    secret = _find_secret(robot_ip)
    return _proxy(get_map, robot_ip, secret, map_name)


@router.post("/{robot_ip}/maps", status_code=201)
def api_create_robot_map(robot_ip: str, body: dict):
    """로봇 맵 생성"""
    secret = _find_secret(robot_ip)
    return _proxy(create_map, robot_ip, secret, body)


@router.put("/{robot_ip}/maps/{map_name}")
def api_update_robot_map(robot_ip: str, map_name: str, body: dict):
    """로봇 맵 수정"""
    secret = _find_secret(robot_ip)
    return _proxy(update_map, robot_ip, secret, map_name, body)


@router.delete("/{robot_ip}/maps/{map_name}")
def api_delete_robot_map(robot_ip: str, map_name: str):
    """로봇 맵 삭제"""
    secret = _find_secret(robot_ip)
    return _proxy(delete_map, robot_ip, secret, map_name)


@router.patch("/{robot_ip}/maps/{map_name}")
def api_patch_robot_map(robot_ip: str, map_name: str, body: dict):
    """로봇 맵 부분 수정"""
    secret = _find_secret(robot_ip)
    return _proxy(patch_map, robot_ip, secret, map_name, body)


# ── 로봇 프록시: /chassis ─────────────────────────────────────

@router.post("/{robot_ip}/chassis/pose")
def api_set_chassis_pose(robot_ip: str, body: dict):
    """로봇 포즈(위치·방향) 설정"""
    body["adjust_position"] = True
    secret = _find_secret(robot_ip)
    return _proxy(set_chassis_pose, robot_ip, secret, body)


# ── 로봇 프록시: /mappings ───────────────────────────────────

@router.get("/{robot_ip}/mappings")
def api_get_mappings(robot_ip: str):
    """맵핑 목록 조회 (로봇 직접 통신)"""
    secret = _find_secret(robot_ip)
    return _proxy(get_mappings, robot_ip, secret)


@router.post("/{robot_ip}/mappings", status_code=201)
def api_create_mapping(robot_ip: str, body: dict):
    """맵핑 시작"""
    secret = _find_secret(robot_ip)
    return _proxy(create_mapping, robot_ip, secret, body)


@router.put("/{robot_ip}/mappings")
def api_update_mapping(robot_ip: str, body: dict):
    """맵핑 수정"""
    secret = _find_secret(robot_ip)
    return _proxy(update_mapping, robot_ip, secret, body)


@router.delete("/{robot_ip}/mappings")
def api_delete_mapping(robot_ip: str):
    """맵핑 삭제"""
    secret = _find_secret(robot_ip)
    return _proxy(delete_mapping, robot_ip, secret)


@router.patch("/{robot_ip}/mappings")
def api_patch_mapping(robot_ip: str, body: dict):
    """맵핑 부분 수정"""
    secret = _find_secret(robot_ip)
    return _proxy(patch_mapping, robot_ip, secret, body)


# ── 로봇 프록시: /mappings/current ───────────────────────────

@router.get("/{robot_ip}/mappings/current")
def api_get_current_mapping(robot_ip: str):
    """현재 맵핑 조회"""
    secret = _find_secret(robot_ip)
    return _proxy(get_current_mapping, robot_ip, secret)


@router.post("/{robot_ip}/mappings/current", status_code=201)
def api_create_current_mapping(robot_ip: str, body: dict):
    """현재 맵핑 시작"""
    secret = _find_secret(robot_ip)
    return _proxy(create_current_mapping, robot_ip, secret, body)


@router.put("/{robot_ip}/mappings/current")
def api_update_current_mapping(robot_ip: str, body: dict):
    """현재 맵핑 수정"""
    secret = _find_secret(robot_ip)
    return _proxy(update_current_mapping, robot_ip, secret, body)


@router.delete("/{robot_ip}/mappings/current")
def api_delete_current_mapping(robot_ip: str):
    """현재 맵핑 중지"""
    secret = _find_secret(robot_ip)
    return _proxy(delete_current_mapping, robot_ip, secret)


@router.patch("/{robot_ip}/mappings/current")
def api_patch_current_mapping(robot_ip: str, body: dict):
    """현재 맵핑 부분 수정"""
    secret = _find_secret(robot_ip)
    return _proxy(patch_current_mapping, robot_ip, secret, body)


# ── 로봇 프록시: /mappings/{id} (parametric — /current 뒤에 위치) ──

@router.get("/{robot_ip}/mappings/{mapping_id}")
def api_get_mapping_by_id(robot_ip: str, mapping_id: int):
    """맵핑 단건 조회 (로봇 직접 통신)"""
    secret = _find_secret(robot_ip)
    return _proxy(get_mapping_by_id, robot_ip, secret, mapping_id)


# ── WebSocket: 실시간 맵핑 데이터 중계 ───────────────────────

@router.websocket("/ws/{robot_ip}")
async def ws_map_relay(websocket: WebSocket, robot_ip: str, topics: Optional[str] = Query(None)):
    """
    프론트엔드 ↔ FastAPI ↔ 로봇 WebSocket 릴레이.

    연결 시 자동으로 맵핑 관련 토픽을 구독하고,
    로봇에서 수신한 데이터를 프론트엔드로 실시간 전달합니다.
    프론트엔드에서 보내는 메시지(enable_topic/disable_topic 등)는 로봇으로 전달됩니다.

    topics 파라미터로 구독할 토픽을 쉼표로 구분하여 지정 가능.
    예: ?topics=/tracked_pose,/trajectory
    """
    secret: Optional[str] = None
    for r in ROBOTS:
        if r["ip"] == robot_ip:
            secret = r["secret"]
            break
    if secret is None:
        await websocket.close(code=4004, reason=f"로봇을 찾을 수 없습니다: {robot_ip}")
        return

    await websocket.accept()

    topic_list = [t.strip() for t in topics.split(",")] if topics else None
    relay = RobotWSRelay(robot_ip, secret, topics=topic_list)
    relay.start()

    try:
        while True:
            try:
                client_msg = await asyncio.wait_for(
                    websocket.receive_text(), timeout=0.05
                )
                relay.send_to_robot(client_msg)
            except asyncio.TimeoutError:
                pass

            messages = relay.poll()
            for msg in messages:
                await websocket.send_text(msg)

            if not messages:
                await asyncio.sleep(0.02)

    except WebSocketDisconnect:
        pass
    finally:
        relay.stop()
