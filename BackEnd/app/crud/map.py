import json

from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from app.models.map import Business, Area, RobotMap, MapPOI, MapLine


# ── Business CRUD ─────────────────────────────────────────────

def get_businesses(db: Session) -> list[dict]:
    items = (
        db.query(Business)
        .join(RobotMap, Business.business_id == RobotMap.business_id)
        .filter(
            Business.is_active == True,
            RobotMap.is_active == True,
            RobotMap.image_url.isnot(None),
        )
        .distinct()
        .order_by(Business.name)
        .all()
    )
    return [
        {
            "business_id": b.business_id,
            "name": b.name,
            "areas": [
                {"area_id": a.area_id, "name": a.name}
                for a in b.areas if a.is_active
            ],
            "created_at": b.created_at,
            "updated_at": b.updated_at,
        }
        for b in items
    ]


def create_business(db: Session, name: str) -> dict:
    exists = db.query(Business).filter(Business.name == name).first()
    if exists:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"이미 존재하는 사업장입니다: {name}")
    biz = Business(name=name)
    db.add(biz)
    db.commit()
    db.refresh(biz)
    return {"business_id": biz.business_id, "name": biz.name, "created_at": biz.created_at, "updated_at": biz.updated_at}


def delete_business(db: Session, business_id: int) -> dict:
    biz = db.query(Business).filter(Business.business_id == business_id).first()
    if not biz:
        raise HTTPException(status_code=404, detail="사업장을 찾을 수 없습니다.")
    biz.is_active = False
    db.commit()
    return {"message": f"사업장 '{biz.name}'이(가) 비활성화되었습니다.", "business_id": business_id}


# ── Area CRUD ─────────────────────────────────────────────────

def get_areas(db: Session, business_id: int) -> list[dict]:
    items = (
        db.query(Area)
        .filter(Area.business_id == business_id, Area.is_active == True)
        .order_by(Area.name)
        .all()
    )
    return [
        {
            "area_id": a.area_id,
            "business_id": a.business_id,
            "name": a.name,
            "created_at": a.created_at,
            "updated_at": a.updated_at,
        }
        for a in items
    ]


def create_area(db: Session, business_id: int, name: str) -> dict:
    biz = db.query(Business).filter(Business.business_id == business_id).first()
    if not biz:
        raise HTTPException(status_code=404, detail="사업장을 찾을 수 없습니다.")
    exists = db.query(Area).filter(Area.business_id == business_id, Area.name == name).first()
    if exists:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"이미 존재하는 영역입니다: {name}")
    area = Area(business_id=business_id, name=name)
    db.add(area)
    db.commit()
    db.refresh(area)
    return {"area_id": area.area_id, "business_id": area.business_id, "name": area.name, "created_at": area.created_at, "updated_at": area.updated_at}


def delete_area(db: Session, area_id: int) -> dict:
    area = db.query(Area).filter(Area.area_id == area_id).first()
    if not area:
        raise HTTPException(status_code=404, detail="영역을 찾을 수 없습니다.")
    area.is_active = False
    db.commit()
    return {"message": f"영역 '{area.name}'이(가) 비활성화되었습니다.", "area_id": area_id}


# ── RobotMap CRUD ─────────────────────────────────────────────

def _map_to_response(rm: RobotMap) -> dict:
    return {
        "id": rm.id,
        "business_id": rm.business_id,
        "area_id": rm.area_id,
        "robot_sn": rm.robot_sn,
        "mapping_id": rm.mapping_id,
        "name": rm.name,
        "thumbnail_url": rm.thumbnail_url,
        "image_url": rm.image_url,
        "grid_origin_x": rm.grid_origin_x,
        "grid_origin_y": rm.grid_origin_y,
        "grid_resolution": rm.grid_resolution,
        "url": rm.url,
        "start_time": rm.start_time,
        "end_time": rm.end_time,
        "state": rm.state,
        "bag_id": rm.bag_id,
        "bag_url": rm.bag_url,
        "download_url": rm.download_url,
        "trajectories_url": rm.trajectories_url,
        "is_active": rm.is_active,
        "created_at": rm.created_at,
        "updated_at": rm.updated_at,
    }


def save_robot_map(db: Session, data: dict) -> dict:
    """매핑 종료 후 결과를 DB에 저장."""
    business_id = data.get("business_id")
    area_id = data.get("area_id")

    if not business_id or not area_id:
        raise HTTPException(status_code=400, detail="business_id와 area_id는 필수입니다.")

    biz = db.query(Business).filter(Business.business_id == business_id).first()
    if not biz:
        raise HTTPException(status_code=404, detail="사업장을 찾을 수 없습니다.")
    area = db.query(Area).filter(Area.area_id == area_id, Area.business_id == business_id).first()
    if not area:
        raise HTTPException(status_code=404, detail="영역을 찾을 수 없습니다.")

    rm = RobotMap(
        business_id=business_id,
        area_id=area_id,
        robot_sn=data.get("robot_sn"),
        mapping_id=data.get("mapping_id"),
        name=data.get("name"),
        thumbnail_url=data.get("thumbnail_url"),
        image_url=data.get("image_url"),
        grid_origin_x=data.get("grid_origin_x", 0.0),
        grid_origin_y=data.get("grid_origin_y", 0.0),
        grid_resolution=data.get("grid_resolution", 0.0),
        url=data.get("url"),
        start_time=data.get("start_time"),
        end_time=data.get("end_time"),
        state=data.get("state"),
        bag_id=data.get("bag_id"),
        bag_url=data.get("bag_url"),
        download_url=data.get("download_url"),
        trajectories_url=data.get("trajectories_url"),
    )
    db.add(rm)
    db.commit()
    db.refresh(rm)
    return _map_to_response(rm)


def get_maps_by_area(db: Session, area_id: int) -> list[dict]:
    """특정 영역의 맵 목록 조회."""
    items = (
        db.query(RobotMap)
        .filter(RobotMap.area_id == area_id, RobotMap.is_active == True)
        .order_by(RobotMap.id.desc())
        .all()
    )
    return [_map_to_response(m) for m in items]


def get_map_by_id(db: Session, map_id: int) -> dict:
    """맵 단건 조회."""
    rm = db.query(RobotMap).filter(RobotMap.id == map_id).first()
    if not rm:
        raise HTTPException(status_code=404, detail="맵을 찾을 수 없습니다.")
    return _map_to_response(rm)


def delete_map(db: Session, map_id: int) -> dict:
    """맵 비활성화."""
    rm = db.query(RobotMap).filter(RobotMap.id == map_id).first()
    if not rm:
        raise HTTPException(status_code=404, detail="맵을 찾을 수 없습니다.")
    rm.is_active = False
    db.commit()
    return {"message": "맵이 비활성화되었습니다.", "id": map_id}


# ── Map Elements (POI + Line) CRUD ───────────────────────────

def save_map_elements(db: Session, map_id: int, payload: dict) -> dict:
    """맵의 POI·라인을 전체 교체 방식으로 저장한다.

    1) 기존 라인 → POI 순서로 삭제  (FK 참조 순서)
    2) POI 삽입 후 프론트엔드 ID → DB ID 매핑
    3) 라인 삽입 (fromId/toId → DB ID 변환)
    """
    rm = db.query(RobotMap).filter(RobotMap.id == map_id).first()
    if not rm:
        raise HTTPException(status_code=404, detail="맵을 찾을 수 없습니다.")

    # 기존 데이터 삭제 (라인 → POI 순서)
    db.query(MapLine).filter(MapLine.map_id == map_id).delete()
    db.query(MapPOI).filter(MapPOI.map_id == map_id).delete()
    db.flush()

    # POI 삽입
    client_id_to_db_id: dict[str, int] = {}
    for p in payload.get("pois", []):
        poi = MapPOI(
            map_id=map_id,
            name=p.get("name", ""),
            x=p["x"],
            y=p["y"],
            world_x=p.get("worldX"),
            world_y=p.get("worldY"),
            poi_type=p.get("type", "waypoint"),
            phone_number=p.get("phoneNumber"),
            angle=p.get("angle"),
            load_type=p.get("loadType"),
            robot_sns=json.dumps(p["robotSns"]) if p.get("robotSns") else None,
            address=p.get("address"),
            docking_radius=p.get("dockingRadius"),
            area_name=p.get("areaName"),
        )
        db.add(poi)
        db.flush()  # id 확정
        client_id_to_db_id[p["id"]] = poi.id

    # 라인 삽입
    for ln in payload.get("lines", []):
        from_db_id = client_id_to_db_id.get(ln["fromId"])
        to_db_id = client_id_to_db_id.get(ln["toId"])
        if from_db_id is None or to_db_id is None:
            continue  # 참조할 POI가 없으면 건너뛰기

        line = MapLine(
            map_id=map_id,
            from_poi_id=from_db_id,
            to_poi_id=to_db_id,
            from_world_x=ln.get("fromWorldX"),
            from_world_y=ln.get("fromWorldY"),
            to_world_x=ln.get("toWorldX"),
            to_world_y=ln.get("toWorldY"),
            from_ori=ln.get("fromOri"),
            to_ori=ln.get("toOri"),
            direction=ln.get("direction", "forward"),
            line_type=ln.get("lineType", "straight"),
            control_points=json.dumps(ln["controlPoints"]) if ln.get("controlPoints") else None,
            area_name=ln.get("areaName"),
        )
        db.add(line)

    db.commit()
    return {"message": "저장 완료", "map_id": map_id}


def get_map_elements(db: Session, map_id: int) -> dict:
    """맵에 저장된 POI·라인을 프론트엔드 형식으로 반환한다."""
    rm = db.query(RobotMap).filter(RobotMap.id == map_id).first()
    if not rm:
        raise HTTPException(status_code=404, detail="맵을 찾을 수 없습니다.")

    pois = db.query(MapPOI).filter(MapPOI.map_id == map_id, MapPOI.is_active == True).all()
    lines = db.query(MapLine).filter(MapLine.map_id == map_id, MapLine.is_active == True).all()

    # DB ID → 프론트엔드 ID 매핑
    db_id_to_client: dict[int, str] = {}
    poi_list = []
    for p in pois:
        client_id = f"poi-{p.id}"
        db_id_to_client[p.id] = client_id
        poi_list.append({
            "id": client_id,
            "x": p.x,
            "y": p.y,
            "worldX": p.world_x,
            "worldY": p.world_y,
            "name": p.name,
            "type": p.poi_type,
            "phoneNumber": p.phone_number,
            "angle": p.angle,
            "loadType": p.load_type,
            "robotSns": json.loads(p.robot_sns) if p.robot_sns else None,
            "address": p.address,
            "dockingRadius": p.docking_radius,
            "areaName": p.area_name,
        })

    line_list = []
    for ln in lines:
        from_client = db_id_to_client.get(ln.from_poi_id)
        to_client = db_id_to_client.get(ln.to_poi_id)
        if not from_client or not to_client:
            continue
        line_list.append({
            "id": f"line-{ln.id}",
            "fromId": from_client,
            "toId": to_client,
            "fromWorldX": ln.from_world_x,
            "fromWorldY": ln.from_world_y,
            "toWorldX": ln.to_world_x,
            "toWorldY": ln.to_world_y,
            "fromOri": ln.from_ori,
            "toOri": ln.to_ori,
            "direction": ln.direction,
            "lineType": ln.line_type,
            "controlPoints": json.loads(ln.control_points) if ln.control_points else None,
            "areaName": ln.area_name,
        })

    return {"pois": poi_list, "lines": line_list}


def get_charging_pois(db: Session, map_id: int):
    """충전소 타입 POI 중 월드 좌표가 유효한 것만 반환."""
    return (
        db.query(MapPOI)
        .filter(
            MapPOI.map_id == map_id,
            MapPOI.poi_type == "charging",
            MapPOI.is_active == True,
            MapPOI.world_x.isnot(None),
            MapPOI.world_y.isnot(None),
        )
        .all()
    )
