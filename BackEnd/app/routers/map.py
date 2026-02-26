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
    update_map_by_id,
    download_map_image,
    restart_robot_service,
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
    get_current_map,
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
        detail=f"등록된 로봇을 찾지 못했습니다: {robot_ip}",
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
            detail=f"로봇 API 오류가 발생했습니다 ({exc.response.status_code if exc.response else '?'}): {resp_text or exc}",
        )
    except Exception as exc:
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"로봇 API 호출에 실패했습니다: {type(exc).__name__}: {exc}",
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


def _correct_map_grid_origin(db: Session, map_id: int) -> bool:
    """DB 맵의 grid_origin이 실제 로봇 맵과 다르면 보정.

    맵핑 원시 데이터의 grid_origin과 로봇이 서비스 재시작 후 만든
    실제 맵의 grid_origin이 달라지는 문제를 감지하고 자동 수정한다.
    DB grid_origin, image_url, download_url(JSON) 모두 갱신.

    Returns: 보정 수행 시 True, 불필요하거나 실패 시 False.
    """
    import json as _json

    rm = db.query(RobotMap).filter(RobotMap.id == map_id, RobotMap.is_active == True).first()
    if not rm or not rm.robot_sn:
        return False

    source_robot = db.query(Robot).filter(
        Robot.serial_number == rm.robot_sn, Robot.is_active == True
    ).first()
    if not source_robot or not source_robot.ip_address:
        return False

    source_ip = source_robot.ip_address
    try:
        source_secret = _find_secret(source_ip)
    except HTTPException:
        return False

    try:
        maps_list = get_maps(source_ip, source_secret)
        if not isinstance(maps_list, list) or not maps_list:
            return False

        actual_map_id = maps_list[0]["id"]
        actual_detail = get_robot_map_by_id(source_ip, source_secret, actual_map_id)
        actual_gx = float(actual_detail.get("grid_origin_x", 0))
        actual_gy = float(actual_detail.get("grid_origin_y", 0))
        actual_res = float(actual_detail.get("grid_resolution", 0.05))

        db_gx = float(rm.grid_origin_x or 0)
        db_gy = float(rm.grid_origin_y or 0)

        if abs(db_gx - actual_gx) < 0.1 and abs(db_gy - actual_gy) < 0.1:
            return False  # 보정 불필요

        print(f"[map-correct] grid_origin 불일치 감지 (map_id={map_id}): "
              f"DB=({db_gx}, {db_gy}) vs 로봇=({actual_gx}, {actual_gy})")

        # ── 1) DB grid_origin 갱신 ──
        rm.grid_origin_x = actual_gx
        rm.grid_origin_y = actual_gy
        rm.grid_resolution = actual_res

        # ── 2) 맵 이미지 재다운로드 ──
        try:
            img_bytes = download_map_image(source_ip, source_secret, actual_map_id)
            img_filename = f"map_img_{uuid.uuid4().hex[:12]}.png"
            img_filepath = STATIC_MAPS_DIR / img_filename
            img_filepath.write_bytes(img_bytes)
            rm.image_url = f"/static/maps/{img_filename}"
        except Exception as img_err:
            print(f"[map-correct] 이미지 갱신 실패 (무시): {img_err}")

        # ── 3) JSON 매핑 데이터의 grid_origin 갱신 ──
        if rm.download_url and rm.download_url.startswith("/static/"):
            try:
                json_path = Path(__file__).resolve().parent.parent.parent / rm.download_url.lstrip("/")
                if json_path.exists():
                    raw = _json.loads(json_path.read_text())
                    if isinstance(raw, list):
                        raw = raw[0] if raw else {}
                    raw["grid_origin_x"] = actual_gx
                    raw["grid_origin_y"] = actual_gy
                    raw["grid_resolution"] = actual_res
                    new_json_name = f"map_data_{uuid.uuid4().hex[:12]}.json"
                    new_json_path = STATIC_MAPS_DIR / new_json_name
                    new_json_path.write_text(_json.dumps(raw))
                    rm.download_url = f"/static/maps/{new_json_name}"
            except Exception as json_err:
                print(f"[map-correct] JSON 갱신 실패 (무시): {json_err}")

        db.commit()
        print(f"[map-correct] 보정 완료: grid_origin=({actual_gx}, {actual_gy}), "
              f"image={rm.image_url}, json={rm.download_url}")
        return True

    except Exception as e:
        print(f"[map-correct] 보정 실패 (로봇 연결 문제?): {e}")
        return False


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
            detail=f"로봇을 찾지 못했습니다: {sn}",
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
            detail=f"로봇에 연결하지 못했습니다: {exc}",
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
    try:
        items = get_businesses(db)
        return {"total": len(items), "items": items}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"사업장 목록 조회 에 실패했습니다: {e}")


@router.post("/businesses", status_code=201)
def api_create_business(body: dict, db: Session = Depends(get_db)):
    """사업장 생성"""
    try:
        name = body.get("name", "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="사업장 이름은 필수입니다.")
        return create_business(db, name)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"사업장 생성 에 실패했습니다: {e}")


@router.delete("/businesses/{business_id}")
def api_delete_business(business_id: int, db: Session = Depends(get_db)):
    """사업장 비활성화"""
    try:
        return delete_business(db, business_id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"사업장 삭제 에 실패했습니다: {e}")


# ── Area (영역) CRUD ──────────────────────────────────────────

@router.get("/businesses/{business_id}/areas")
def api_get_areas(business_id: int, db: Session = Depends(get_db)):
    """해당 사업장의 영역 목록 조회 (드롭다운용)"""
    try:
        items = get_areas(db, business_id)
        return {"total": len(items), "items": items}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"영역 목록 조회 에 실패했습니다: {e}")


@router.post("/areas", status_code=201)
def api_create_area(body: dict, db: Session = Depends(get_db)):
    """영역 생성"""
    try:
        business_id = body.get("business_id")
        name = body.get("name", "").strip()
        if not business_id:
            raise HTTPException(status_code=400, detail="business_id는 필수입니다.")
        if not name:
            raise HTTPException(status_code=400, detail="영역 이름은 필수입니다.")
        return create_area(db, business_id, name)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"영역 생성 에 실패했습니다: {e}")


@router.delete("/areas/{area_id}")
def api_delete_area(area_id: int, db: Session = Depends(get_db)):
    """영역 비활성화"""
    try:
        return delete_area(db, area_id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"영역 삭제 에 실패했습니다: {e}")


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
    except Exception as e:
        print(f"[save_map] 이미지 다운로드 실패 ({url}): {e}")
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
    except Exception as e:
        print(f"[save_map] 맵 데이터 다운로드 실패 ({download_url}): {e}")
        return None


def _download_robot_file(url: str, prefix: str, ext: str, secret: str | None = None) -> str | None:
    """로봇 파일(bag, trajectories 등)을 다운로드하여 /static/maps/에 저장."""
    if not url:
        return None
    try:
        headers = {"Secret": secret} if secret else {}
        res = http_requests.get(url, headers=headers, timeout=60)
        res.raise_for_status()
        filename = f"{prefix}_{uuid.uuid4().hex[:12]}{ext}"
        filepath = STATIC_MAPS_DIR / filename
        filepath.write_bytes(res.content)
        return f"/static/maps/{filename}"
    except Exception as e:
        print(f"[save_map] 파일 다운로드 실패 ({url}): {e}")
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
        except Exception as e:
            print(f"[save_map] 로봇 Secret 조회 에 실패했습니다: {e}")
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

    # bag 파일(.bag) 다운로드 저장
    if body.get("bag_url"):
        local_path = _download_robot_file(body["bag_url"], "map_bag", ".bag", robot_secret)
        if local_path:
            body["bag_url"] = local_path

    # trajectories 데이터(.json) 다운로드 저장
    if body.get("trajectories_url"):
        local_path = _download_robot_file(body["trajectories_url"], "map_traj", ".json", robot_secret)
        if local_path:
            body["trajectories_url"] = local_path

    try:
        result = save_robot_map(db, body)
    except Exception as e:
        print(f"[save_map] DB 저장 에 실패했습니다: {e}")
        raise HTTPException(status_code=500, detail=f"맵 DB 저장 에 실패했습니다: {e}")

    # 맵 저장 성공 시, 연결 가능한 모든 로봇의 area_id 업데이트
    area_id = body.get("area_id")
    if area_id:
        try:
            _update_robots_area(db, str(area_id))
        except Exception as e:
            print(f"[save_map] 로봇 area_id 업데이트 에 실패했습니다: {e}")

    # ── 자동 동기화: 서버 데이터 기반으로 즉시 동기화 + 후속 DB 보정 ──
    saved_map_id = result.get("id")
    source_sn = body.get("robot_sn")
    area_name = body.get("name", "synced-map")
    if saved_map_id and source_sn:
        import threading

        def _auto_sync():
            from app.database import SessionLocal
            sync_db = SessionLocal()
            try:
                source_robot = sync_db.query(Robot).filter(
                    Robot.serial_number == source_sn, Robot.is_active == True
                ).first()
                source_ip = source_robot.ip_address if source_robot else None
                if not source_ip:
                    print(f"[auto-sync] 소스 로봇 IP를 찾지 못했습니다: {source_sn}")
                    return

                # ── 1) 서버 데이터 기반 즉시 동기화 (소스 로봇 대기 불필요) ──
                targets = [r["ip"] for r in ROBOTS if r["ip"] != source_ip]
                if targets:
                    print(f"[auto-sync] 서버 데이터 기반 즉시 동기화: → {targets}")
                    for target_ip in targets:
                        try:
                            api_sync_map_to_robot(
                                map_id=saved_map_id,
                                body={"robot_ip": target_ip, "area_name": area_name, "method": "full"},
                                db=sync_db,
                            )
                            print(f"[auto-sync] ✓ {target_ip} 동기화 완료")
                        except Exception as e:
                            print(f"[auto-sync] ✗ {target_ip} 동기화 에 실패했습니다: {e}")
                else:
                    print("[auto-sync] 동기화할 타겟 로봇이 없습니다.")

                # ── 2) 소스 로봇의 새 맵 생성 대기 → DB 보정 (grid_origin + image + JSON) ──
                import time as _time
                source_secret = _find_secret(source_ip)
                old_maps = get_maps(source_ip, source_secret)
                old_map_id = old_maps[0]["id"] if isinstance(old_maps, list) and old_maps else None
                old_map_version = old_maps[0].get("map_version", 0) if old_map_id else 0

                print(f"[auto-sync] DB 보정용 새 맵 대기 중... (현재 id={old_map_id}, ver={old_map_version})")
                new_map_found = False
                for wait_i in range(24):  # 최대 120초 (5초 × 24)
                    _time.sleep(5)
                    cur_maps = get_maps(source_ip, source_secret)
                    if isinstance(cur_maps, list) and cur_maps:
                        cur_id = cur_maps[0]["id"]
                        cur_ver = cur_maps[0].get("map_version", 0)
                        if cur_id != old_map_id or cur_ver != old_map_version:
                            print(f"[auto-sync] 새 맵 감지: id={cur_id}, ver={cur_ver} ({(wait_i+1)*5}초)")
                            new_map_found = True
                            break
                    if wait_i % 6 == 5:
                        print(f"[auto-sync] 대기 중... ({(wait_i+1)*5}초 경과)")

                if not new_map_found:
                    print("[auto-sync] 120초 내 새 맵 미생성 — DB 보정은 api_get_default_map에서 재시도됨")
                    return

                # ── _correct_map_grid_origin()으로 한 번에 보정 (grid_origin + image + JSON) ──
                corrected = _correct_map_grid_origin(sync_db, saved_map_id)
                if corrected:
                    print("[auto-sync] DB 보정 완료 (grid_origin + image + JSON)")
                else:
                    print("[auto-sync] DB 보정 불필요 또는 실패 — api_get_default_map에서 재시도됨")

            except Exception as e:
                print(f"[auto-sync] 오류: {e}")
            finally:
                sync_db.close()

        threading.Thread(target=_auto_sync, daemon=True).start()

    return result


@router.get("/default-map")
def api_get_default_map(db: Session = Depends(get_db)):
    """가장 최근 업데이트된 활성 맵 정보 반환 (모니터링 페이지 기본값용)"""
    try:
        latest = (
            db.query(RobotMap)
            .filter(RobotMap.is_active == True)
            .order_by(RobotMap.updated_at.desc())
            .first()
        )
        if not latest:
            return {"image_url": None, "grid_origin_x": 0, "grid_origin_y": 0, "grid_resolution": 0.05, "area_id": None}

        # grid_origin 보정 확인 (로봇 연결 가능 시 자동 보정, 실패해도 기존 값 반환)
        if _correct_map_grid_origin(db, latest.id):
            db.refresh(latest)

        return {
            "image_url": latest.image_url,
            "grid_origin_x": float(latest.grid_origin_x) if latest.grid_origin_x else 0,
            "grid_origin_y": float(latest.grid_origin_y) if latest.grid_origin_y else 0,
            "grid_resolution": float(latest.grid_resolution) if latest.grid_resolution else 0.05,
            "area_id": latest.area_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"기본 맵 조회 중 오류가 발생했습니다: {e}")


@router.get("/areas/{area_id}/maps")
def api_get_maps_by_area(area_id: int, db: Session = Depends(get_db)):
    """해당 영역의 저장된 맵 목록 조회 (드롭다운용)"""
    try:
        items = get_maps_by_area(db, area_id)
        return {"total": len(items), "items": items}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"맵 목록 조회 에 실패했습니다: {e}")


@router.get("/maps/{map_id}")
def api_get_map_detail(map_id: int, db: Session = Depends(get_db)):
    """맵 단건 조회"""
    try:
        return get_map_by_id(db, map_id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"맵 상세 조회 에 실패했습니다: {e}")


@router.delete("/maps/{map_id}")
def api_delete_saved_map(map_id: int, db: Session = Depends(get_db)):
    """맵 비활성화"""
    try:
        return crud_delete_map(db, map_id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"맵 삭제 에 실패했습니다: {e}")


@router.post("/maps/{map_id}/sync-to-robot")
def api_sync_map_to_robot(map_id: int, body: dict, db: Session = Depends(get_db)):
    """맵 동기화: 소스 로봇의 맵 데이터를 타겟 로봇에 동기화.

    body: {
        robot_ip: str,          # 타겟 로봇 IP (필수)
        area_name: str,         # 맵 이름 (기본 "synced-map")
        method: "patch"|"full"  # 동기화 방식 (기본 "patch")
    }

    method 옵션:
      - "patch": 오버레이(POI·경로)만 동기화 (빠름, 타겟 로봇의 SLAM 유지)
      - "full":  소스 매핑의 SLAM + 이미지 + 오버레이 전체 업로드 후 current-map 설정
                 ※ 타겟 로봇의 기존 맵 삭제됨, 재부팅 시 py_axbot이 자체 매핑으로 복원할 수 있음
    """
    import json as _json

    robot_ip = body.get("robot_ip")
    area_name = body.get("area_name", "synced-map")
    sync_method = body.get("method", "patch")  # "patch" or "full"
    if not robot_ip:
        raise HTTPException(status_code=400, detail="robot_ip는 필수입니다.")

    target_secret = _find_secret(robot_ip)

    # DB에서 맵 조회
    rm = db.query(RobotMap).filter(RobotMap.id == map_id).first()
    if not rm:
        raise HTTPException(status_code=404, detail="맵을 찾지 못했습니다.")

    # ── 1) 서버에 저장된 매핑 데이터 로드 ──
    mapping_data = None
    if rm.download_url and rm.download_url.startswith("/static/"):
        local_path = Path(__file__).resolve().parent.parent.parent / rm.download_url.lstrip("/")
        if local_path.exists():
            import json as _json_load
            mapping_data = _json_load.loads(local_path.read_text())
            print(f"[sync] 서버 매핑 데이터 로드: {rm.download_url}")

    if not mapping_data:
        raise HTTPException(
            status_code=400,
            detail="서버에 저장된 매핑 데이터가 없습니다. 맵을 다시 저장해주세요.",
        )

    # ── 2) 충전소 오버레이 구성 (DB 기반) ──
    overlay_data = {"type": "FeatureCollection", "features": []}
    overlay_synced = False
    overlay_error = None
    try:
        charging_pois = get_charging_pois(db, map_id)
        if charging_pois:
            new_features = _build_charging_overlay_features(charging_pois)
            print(f"[sync] 충전소 POI {len(charging_pois)}개 → Feature {len(new_features)}개 생성")
            overlay_data["features"] = new_features
            overlay_synced = True
        else:
            print("[sync] 충전소 POI 없음")
    except Exception as e:
        overlay_error = str(e)
        print(f"[sync] 충전소 오버레이 처리 에 실패했습니다: {e}")

    print(f"[sync] 타겟: {robot_ip} ({sync_method}), "
          f"carto_map: {len(mapping_data.get('carto_map', ''))}자, "
          f"오버레이: {len(overlay_data.get('features', []))}개")

    # ── 3) full 방식: 서버 데이터로 전체 동기화 ──
    if sync_method == "full":
        return _sync_full_from_server(
            mapping_data, robot_ip, target_secret, area_name,
            overlay_data, overlay_synced, overlay_error,
        )

    # ── 4) patch 방식: 오버레이만 동기화 ──
    return _sync_patch_to_robot(
        robot_ip, target_secret,
        overlay_data, overlay_synced, overlay_error,
    )


def _sync_full_from_server(
    mapping_data: dict,
    target_ip: str, target_secret: str, area_name: str,
    overlay_data: dict, overlay_synced: bool, overlay_error: str | None,
) -> dict:
    """Full 동기화 (서버 데이터 기반): 서버에 저장된 매핑 데이터로 타겟 로봇의 맵 전체 교체.

    전략:
      1) 서버 JSON의 carto_map + occupancy_grid + grid_origin 사용
      2) 타겟 로봇의 네이티브 맵에 PUT /maps/{id} 로 전체 교체
      3) PUT 후 서비스 재시작 → py_axbot이 carto_map에서 맵 재생성
      4) PUT 실패 시 fallback: POST sync 맵 생성
    """
    import json as _json

    carto_map = mapping_data.get("carto_map", "")
    if not carto_map:
        raise HTTPException(status_code=400, detail="매핑 데이터에 SLAM 데이터(carto_map)가 없습니다.")

    occupancy_grid = mapping_data.get("occupancy_grid", "")
    grid_x = mapping_data.get("grid_origin_x", 0)
    grid_y = mapping_data.get("grid_origin_y", 0)
    grid_res = mapping_data.get("grid_resolution", 0.05)

    print(f"[sync:full] 서버 데이터 → {target_ip}: "
          f"carto_map={len(carto_map)}자, grid_origin=({grid_x}, {grid_y})")

    overlay_json = _json.dumps(overlay_data)

    # ── 1. 타겟 로봇의 맵 목록 → 네이티브/sync 분류 ──
    native_map_id = None
    native_map_name = None
    sync_map_ids = []
    try:
        old_maps = get_maps(target_ip, target_secret)
        if isinstance(old_maps, list):
            for m in old_maps:
                mid = m.get("id")
                mname = m.get("map_name", "")
                if "-sync-" in str(mname):
                    sync_map_ids.append(mid)
                else:
                    native_map_id = mid
                    native_map_name = mname
    except Exception:
        pass

    print(f"[sync:full] 타겟 {target_ip}: native={native_map_id}({native_map_name}), "
          f"sync맵={sync_map_ids}")

    # ── 2. 네이티브 맵 PUT 전체 교체 시도 (재부팅 생존) ──
    put_success = False
    if native_map_id is not None:
        put_data = {
            "map_name": native_map_name or area_name,
            "carto_map": carto_map,
            "occupancy_grid": occupancy_grid,
            "grid_origin_x": grid_x,
            "grid_origin_y": grid_y,
            "grid_resolution": grid_res,
            "overlays": overlay_json,
        }
        try:
            update_map_by_id(target_ip, target_secret, native_map_id, put_data)
            put_success = True
            print(f"[sync:full] ✓ 네이티브 맵 PUT 성공: id={native_map_id}")
        except Exception as e:
            print(f"[sync:full] ✗ 네이티브 맵 PUT 실패: {e} → fallback 진행")

    if put_success:
        # PUT 후 서비스 재시작 → py_axbot이 carto_map에서 맵 재생성
        try:
            restart_robot_service(target_ip, target_secret)
            print(f"[sync:full] 서비스 재시작 요청 완료 (약 60-90초)")
        except Exception as e:
            print(f"[sync:full] 서비스 재시작 에 실패했습니다: {e}")

        # 이전 sync 맵 삭제
        for sid in sync_map_ids:
            try:
                delete_map_by_id(target_ip, target_secret, sid)
                print(f"[sync:full] sync 맵 삭제: id={sid}")
            except Exception:
                pass

        return {
            "message": "맵 동기화 완료 (서버 데이터 → 네이티브 맵 전체 교체)",
            "robot_ip": target_ip,
            "robot_map_id": native_map_id,
            "overlay_features": len(overlay_data.get("features", [])),
            "overlay_synced": overlay_synced,
            "overlay_error": overlay_error,
            "method": "full_put",
            "carto_map_size": len(carto_map),
        }

    # ── 3. PUT 실패 fallback: POST sync 맵 생성 ──
    print("[sync:full] fallback: POST sync 맵 생성")

    # 네이티브 맵에 overlay만 PATCH
    if native_map_id is not None:
        try:
            patch_map_by_id(target_ip, target_secret, native_map_id, {
                "overlays": overlay_json,
            })
            print(f"[sync:full:fb] 네이티브 맵 overlay PATCH: id={native_map_id}")
        except Exception as e:
            print(f"[sync:full:fb] overlay PATCH 에 실패했습니다: {e}")

    # 이전 sync 맵 삭제
    for sid in sync_map_ids:
        try:
            delete_map_by_id(target_ip, target_secret, sid)
        except Exception:
            pass

    # POST sync 맵 생성 (재부팅 시 삭제됨)
    sync_map_name = f"{area_name}-sync-{target_ip.split('.')[-1]}"
    post_data = {
        "map_name": sync_map_name,
        "carto_map": carto_map,
        "occupancy_grid": occupancy_grid,
        "grid_origin_x": grid_x,
        "grid_origin_y": grid_y,
        "grid_resolution": grid_res,
        "overlays": overlay_json,
    }

    try:
        created = create_map(target_ip, target_secret, post_data)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"타겟 로봇 맵 생성 에 실패했습니다: {e}")

    new_map_id = created.get("id")
    print(f"[sync:full:fb] sync 맵 생성: id={new_map_id}")

    try:
        set_current_map(target_ip, target_secret, {"map_id": new_map_id})
        print(f"[sync:full:fb] current-map → sync id={new_map_id}")
    except Exception as e:
        print(f"[sync:full:fb] current-map 설정 에 실패했습니다: {e}")

    return {
        "message": "맵 동기화 완료 (fallback: sync 맵 — 재부팅 시 삭제됨)",
        "robot_ip": target_ip,
        "robot_map_id": new_map_id,
        "native_map_id": native_map_id,
        "overlay_features": len(overlay_data.get("features", [])),
        "overlay_synced": overlay_synced,
        "overlay_error": overlay_error,
        "method": "full_fallback",
        "carto_map_size": len(carto_map),
    }


def _sync_patch_to_robot(
    target_ip: str, target_secret: str,
    overlay_data: dict, overlay_synced: bool, overlay_error: str | None,
) -> dict:
    """Patch 동기화: 오버레이(충전소 POI)만 타겟 로봇의 현재 맵에 PATCH."""
    import json as _json

    target_map_id = None

    # current-map 확인
    try:
        current = get_current_map(target_ip, target_secret)
        if isinstance(current, dict) and current.get("id"):
            target_map_id = current["id"]
    except Exception:
        pass

    # current-map 없으면 맵 목록에서 첫 번째 사용
    if target_map_id is None:
        try:
            maps_list = get_maps(target_ip, target_secret)
            if isinstance(maps_list, list) and maps_list:
                target_map_id = maps_list[0]["id"]
        except Exception:
            pass

    if target_map_id is None:
        raise HTTPException(
            status_code=502,
            detail="타겟 로봇에 맵이 없습니다. full 동기화를 사용하세요.",
        )

    patch_data = {"overlays": _json.dumps(overlay_data)}

    try:
        patch_map_by_id(target_ip, target_secret, target_map_id, patch_data)
        print(f"[sync:patch] ✓ PATCH 완료: {target_ip} id={target_map_id}")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"타겟 로봇 맵 PATCH 에 실패했습니다: {e}")

    return {
        "message": "오버레이 동기화 완료",
        "robot_ip": target_ip,
        "robot_map_id": target_map_id,
        "overlay_features": len(overlay_data.get("features", [])),
        "overlay_synced": overlay_synced,
        "overlay_error": overlay_error,
        "method": "patch",
    }


@router.get("/{robot_ip}/maps/{robot_map_id}/detail")
def api_get_robot_map_detail(robot_ip: str, robot_map_id: int):
    """로봇에 저장된 맵 상세 정보 조회 (overlays 확인용)"""
    try:
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
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"로봇 맵 상세 조회 중 오류가 발생했습니다: {e}")


# ── 맵 요소 (POI·라인) 저장 / 조회 ──────────────────────────

@router.put("/maps/{map_id}/elements")
def api_save_map_elements(map_id: int, body: dict, db: Session = Depends(get_db)):
    """맵의 POI·라인을 전체 교체 방식으로 저장"""
    try:
        return save_map_elements(db, map_id, body)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"맵 요소 저장 에 실패했습니다: {e}")


@router.get("/maps/{map_id}/elements")
def api_get_map_elements(map_id: int, db: Session = Depends(get_db)):
    """맵에 저장된 POI·라인 조회"""
    try:
        return get_map_elements(db, map_id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"맵 요소 조회 에 실패했습니다: {e}")


# ── 이미지 프록시 ─────────────────────────────────────────────

@router.get("/proxy-image")
def api_proxy_image(url: str = Query(..., description="로봇 이미지 URL")):
    """로봇의 이미지를 프록시하여 CORS 문제 없이 프론트엔드에 전달."""
    try:
        res = http_requests.get(url, timeout=10)
        res.raise_for_status()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"이미지를 가져오지 못했습니다: {exc}")
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


@router.post("/relocalize")
def api_relocalize_robots(body: dict, db: Session = Depends(get_db)):
    """선택된 로봇들의 위치를 충전소 도킹 포인트 좌표로 재조정.

    body: {
        robot_ips: list[str]   # 위치재조정할 로봇 IP 목록
    }

    각 로봇의 DB 충전소 POI(Robot.charging_id → MapPOI)를 조회하여
    도킹 포인트 좌표를 계산하고 set_chassis_pose로 전송합니다.
    """
    from app.models.map import MapPOI

    robot_ips = body.get("robot_ips", [])
    if not robot_ips:
        raise HTTPException(status_code=400, detail="robot_ips는 필수입니다.")

    # 위치 보정 전 grid_origin 정합성 확인 (잘못된 좌표계 방지)
    _corrected_map_ids: set = set()
    results = []
    for robot_ip in robot_ips:
        result = {"robot_ip": robot_ip, "success": False, "message": ""}
        try:
            secret = _find_secret(robot_ip)
            robot = db.query(Robot).filter(
                Robot.ip_address == robot_ip, Robot.is_active == True
            ).first()
            if not robot:
                result["message"] = "DB에 등록되지 않은 로봇입니다."
                results.append(result)
                continue
            if not robot.charging_id:
                result["message"] = "충전소가 지정되지 않았습니다."
                results.append(result)
                continue

            poi = db.query(MapPOI).filter(
                MapPOI.id == robot.charging_id,
                MapPOI.is_active == True,
            ).first()

            # POI가 속한 맵의 grid_origin 보정 (맵당 1회만)
            if poi and poi.map_id and poi.map_id not in _corrected_map_ids:
                _correct_map_grid_origin(db, poi.map_id)
                _corrected_map_ids.add(poi.map_id)
            if not poi or poi.world_x is None or poi.world_y is None:
                result["message"] = "충전소 POI에 월드 좌표가 없습니다."
                results.append(result)
                continue

            # 도킹 포인트: 충전소 yaw 방향으로 0.9m 앞, 충전소를 바라보는 방향
            yaw_rad = poi.angle if poi.angle is not None else 0.0
            dock_x = poi.world_x + DOCKING_OFFSET * math.cos(yaw_rad)
            dock_y = poi.world_y + DOCKING_OFFSET * math.sin(yaw_rad)
            dock_yaw = yaw_rad + math.pi  # 충전소를 바라보는 방향

            set_chassis_pose(robot_ip, secret, {
                "position": [dock_x, dock_y, 0],
                "ori": dock_yaw,
            })

            result["success"] = True
            result["message"] = (
                f"위치재조정 완료: ({dock_x:.2f}, {dock_y:.2f}, "
                f"θ={math.degrees(dock_yaw):.0f}°)"
            )
            print(f"[relocalize] ✓ {robot_ip}: {result['message']}")

        except HTTPException:
            result["message"] = f"등록되지 않은 로봇: {robot_ip}"
        except Exception as e:
            result["message"] = f"위치재조정 실패: {e}"
            print(f"[relocalize] ✗ {robot_ip}: {e}")

        results.append(result)

    return {"results": results}


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
        await websocket.close(code=4004, reason=f"로봇을 찾지 못했습니다: {robot_ip}")
        return

    await websocket.accept()

    topic_list = [t.strip() for t in topics.split(",")] if topics else None
    relay = RobotWSRelay(robot_ip, secret, topics=topic_list)
    try:
        relay.start()
    except Exception as e:
        print(f"[ws_map_relay] 로봇 WS 릴레이 시작 실패 ({robot_ip}): {e}")
        await websocket.send_text(f'{{"error": "로봇 WebSocket 연결 실패: {e}"}}')
        await websocket.close(code=1011)
        return

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
        print(f"[ws_map_relay] 클라이언트 연결 종료 ({robot_ip})")
    except Exception as e:
        print(f"[ws_map_relay] 릴레이 중 오류 ({robot_ip}): {e}")
    finally:
        relay.stop()
