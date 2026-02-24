import asyncio
import math
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
from app.models.map import RobotMap
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
    get_charging_pois,
)
from app.robot_api.robot_map_service import (
    RobotWSRelay,
    get_maps,
    get_map,
    create_map,
    update_map,
    delete_map,
    patch_map,
    get_map_by_id as get_robot_map_by_id,
    delete_map_by_id,
    patch_map_by_id,
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
    set_current_map,
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


def _update_robots_area(db: Session, area_id: str):
    """연결 가능한 모든 로봇의 area_id를 업데이트한다."""
    robots = db.query(Robot).filter(Robot.is_active == True).all()
    for robot in robots:
        if not robot.ip_address:
            continue
        try:
            res = http_requests.get(
                f"http://{robot.ip_address}:8090/device/info",
                headers={"Secret": _find_secret(robot.ip_address)} if robot.ip_address in [r["ip"] for r in ROBOTS] else {},
                timeout=3,
            )
            res.raise_for_status()
            robot.area_id = area_id
            print(f"[save_map] 로봇 {robot.serial_number} area_id={area_id} 업데이트")
        except Exception:
            print(f"[save_map] 로봇 {robot.serial_number} ({robot.ip_address}) 연결 불가 → 건너뜀")
    db.commit()


DOCKING_OFFSET = 0.9  # 충전소에서 도킹 포인트까지의 거리 (m)


def _build_charging_overlay_features(charging_pois: list) -> list[dict]:
    """충전소 POI 목록을 로봇 오버레이용 GeoJSON Feature 리스트로 변환.

    각 충전소마다 2개의 Feature를 생성:
    - 충전소 (type "9"): 충전기 위치
    - 도킹 포인트 (type "36"): 로봇이 도킹하는 위치 (충전소 yaw 방향 0.9m 앞)
    """
    features = []
    for poi in charging_pois:
        charger_id = uuid.uuid4().hex[:24]
        docking_id = uuid.uuid4().hex[:24]

        # angle: DB에 radian 저장 → degree 문자열로 변환
        yaw_deg = 0.0
        if poi.angle is not None:
            yaw_deg = poi.angle * 180.0 / math.pi
        charger_yaw = str(int(round(yaw_deg)))  # 정수 문자열 ("180", "90" 등)

        # 도킹 포인트: 충전소 yaw 방향으로 DOCKING_OFFSET만큼 앞
        yaw_rad = math.radians(yaw_deg)
        dock_x = poi.world_x + DOCKING_OFFSET * math.cos(yaw_rad)
        dock_y = poi.world_y + DOCKING_OFFSET * math.sin(yaw_rad)
        raw_dock_yaw = int(round((yaw_deg + 180) % 360))
        dock_yaw = str(360 if raw_dock_yaw == 0 else raw_dock_yaw)  # 0° → "360" (1SSS 방식)

        poi_name = poi.name or ""

        # 충전소 Feature (type "9")
        features.append({
            "id": charger_id,
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [poi.world_x, poi.world_y],
            },
            "properties": {
                "deviceIds": None,
                "dockingPointId": docking_id,
                "mapOverlay": True,
                "name": poi_name,
                "subtype": "24v",
                "type": "9",
                "yaw": charger_yaw,
            },
        })

        # 도킹 포인트 Feature (type "36")
        features.append({
            "id": docking_id,
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [dock_x, dock_y],
            },
            "properties": {
                "dockingPointId": charger_id,
                "mapOverlay": True,
                "name": f"{poi_name} Docking Point",
                "type": "36",
                "yaw": dock_yaw,
            },
        })

    return features


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


def _download_robot_map_data(download_url: str, secret: str | None = None) -> str | None:
    """로봇 맵 데이터(JSON)를 다운로드하여 로컬에 저장하고, 서버 경로를 반환."""
    if not download_url:
        return None
    try:
        headers = {"Secret": secret} if secret else {}
        res = http_requests.get(download_url, headers=headers, timeout=30)
        res.raise_for_status()
        filename = f"map_data_{uuid.uuid4().hex[:12]}.json"
        filepath = STATIC_MAPS_DIR / filename
        filepath.write_bytes(res.content)
        return f"/static/maps/{filename}"
    except Exception:
        return None


@router.post("/maps/save", status_code=201)
def api_save_map(body: dict, db: Session = Depends(get_db)):
    """매핑 종료 후 결과를 DB에 저장.
    이미지·맵 데이터를 로봇에서 다운로드하여 로컬 서버에 저장한 뒤 경로를 DB에 기록."""
    # 로봇 secret 조회 (download_url에 필요)
    robot_secret = None
    download_url = body.get("download_url")
    if download_url:
        try:
            from urllib.parse import urlparse
            robot_ip = urlparse(download_url).hostname
            robot_secret = _find_secret(robot_ip)
        except Exception:
            pass

    # 로봇 URL → 로컬 서버 파일로 다운로드
    if body.get("image_url"):
        local_path = _download_robot_image(body["image_url"], "map_img")
        if local_path:
            body["image_url"] = local_path

    if body.get("thumbnail_url"):
        local_path = _download_robot_image(body["thumbnail_url"], "map_thumb")
        if local_path:
            body["thumbnail_url"] = local_path

    # 맵 데이터(JSON) 다운로드 저장
    if download_url:
        local_data_path = _download_robot_map_data(download_url, robot_secret)
        if local_data_path:
            body["download_url"] = local_data_path

    result = save_robot_map(db, body)

    # 맵 저장 성공 시, 연결 가능한 모든 로봇의 area_id 업데이트
    area_id = body.get("area_id")
    if area_id:
        _update_robots_area(db, str(area_id))

    return result


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


@router.post("/maps/{map_id}/sync-to-robot")
def api_sync_map_to_robot(map_id: int, body: dict, db: Session = Depends(get_db)):
    """DB에 저장된 맵 데이터를 대상 로봇에 업로드하고 현재 지도로 설정.
    body: { robot_ip: str, area_name: str }
    """
    import json as _json

    robot_ip = body.get("robot_ip")
    area_name = body.get("area_name", "synced-map")
    if not robot_ip:
        raise HTTPException(status_code=400, detail="robot_ip는 필수입니다.")

    secret = _find_secret(robot_ip)

    # DB에서 맵 조회
    rm = db.query(RobotMap).filter(RobotMap.id == map_id).first()
    if not rm:
        raise HTTPException(status_code=404, detail="맵을 찾을 수 없습니다.")

    # 로컬에 저장된 맵 데이터 파일 읽기
    download_path = rm.download_url
    if not download_path or not download_path.startswith("/static/"):
        raise HTTPException(status_code=400, detail="맵 데이터 파일이 로컬에 저장되어 있지 않습니다. 매핑을 다시 저장해주세요.")

    filepath = STATIC_MAPS_DIR.parent.parent / download_path.lstrip("/")
    if not filepath.exists():
        raise HTTPException(status_code=404, detail=f"맵 데이터 파일을 찾을 수 없습니다: {download_path}")

    map_data = _json.loads(filepath.read_text(encoding="utf-8"))
    map_data["map_name"] = area_name

    # 1) 로봇에 이미 같은 이름의 맵이 있는지 확인
    overlay_synced = False
    overlay_error = None
    robot_map_id = None
    try:
        maps_list = get_maps(robot_ip, secret)
        if isinstance(maps_list, list):
            target = next((m for m in maps_list if m.get("map_name") == area_name), None)
        else:
            target = None
        if target:
            robot_map_id = target["id"]
            print(f"[sync] 기존 맵 재사용: id={robot_map_id}")
    except Exception:
        pass

    # 3) 없으면 새로 업로드
    if robot_map_id is None:
        try:
            result = create_map(robot_ip, secret, map_data)
            robot_map_id = result.get("id")
            print(f"[sync] 맵 생성 완료: id={robot_map_id}")
        except Exception as e:
            print(f"[sync] 맵 생성 실패: {e}")

    if robot_map_id is None:
        raise HTTPException(status_code=502, detail="로봇에 맵을 업로드할 수 없습니다.")

    # 4) 충전소 오버레이 PATCH (set_current_map 전에 수행)
    try:
        charging_pois = get_charging_pois(db, map_id)
        if charging_pois:
            new_features = _build_charging_overlay_features(charging_pois)
            print(f"[sync] 충전소 POI {len(charging_pois)}개 → Feature {len(new_features)}개 생성")

            # 기존 오버레이 가져오기
            existing = get_robot_map_by_id(robot_ip, secret, robot_map_id)
            raw_overlays = existing.get("overlays")
            if isinstance(raw_overlays, str):
                overlay_data = _json.loads(raw_overlays)
            elif isinstance(raw_overlays, dict):
                overlay_data = raw_overlays
            else:
                overlay_data = {"type": "FeatureCollection", "features": []}

            # 기존 충전소(type "9") 및 도킹(type "36") 피처 제거 후 새로 추가
            old_features = [
                f for f in overlay_data.get("features", [])
                if f.get("properties", {}).get("type") not in ("9", "36")
            ]
            overlay_data["features"] = old_features + new_features

            # PATCH (overlays는 JSON 문자열로 전송)
            patch_result = patch_map_by_id(
                robot_ip, secret, robot_map_id,
                {"overlays": _json.dumps(overlay_data)}
            )
            overlay_synced = True
            print(f"[sync] 오버레이 PATCH 완료: {patch_result}")
        else:
            print("[sync] 충전소 POI 없음 → 오버레이 건너뜀")
    except Exception as e:
        overlay_error = str(e)
        print(f"[sync] 오버레이 처리 실패 (맵 동기화는 계속): {e}")

    # 5) 현재 지도 설정
    try:
        result = set_current_map(robot_ip, secret, {"map_id": robot_map_id})
        print(f"[sync] 현재 지도 설정: {result}")
    except Exception as e:
        print(f"[sync] 현재 지도 설정 실패: {e}")

    return {
        "message": "맵 동기화 완료",
        "robot_ip": robot_ip,
        "robot_map_id": robot_map_id,
        "overlay_synced": overlay_synced,
        "overlay_error": overlay_error,
    }


@router.get("/{robot_ip}/maps/{robot_map_id}/detail")
def api_get_robot_map_detail(robot_ip: str, robot_map_id: int):
    """로봇에 저장된 맵 상세 정보 조회 (overlays 확인용)"""
    import json as _json
    secret = _find_secret(robot_ip)
    detail = get_robot_map_by_id(robot_ip, secret, robot_map_id)

    # overlays가 문자열이면 파싱해서 보기 좋게 반환
    raw = detail.get("overlays")
    if isinstance(raw, str):
        try:
            detail["overlays"] = _json.loads(raw)
        except Exception:
            pass
    return detail


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
    secret = _find_secret(robot_ip)
    return _proxy(set_chassis_pose, robot_ip, secret, body)


@router.post("/{robot_ip}/chassis/current-map")
def api_set_current_map(robot_ip: str, body: dict):
    """현재 지도 설정 — {map_id: N}"""
    secret = _find_secret(robot_ip)
    return _proxy(set_current_map, robot_ip, secret, body)


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
