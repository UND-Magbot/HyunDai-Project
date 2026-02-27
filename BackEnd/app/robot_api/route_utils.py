"""
MapLine 그래프 기반 경로 탐색 유틸리티
- BFS로 두 POI 사이의 최단 경로를 찾음
- convoy 진입/복귀 경로, 충전소 이동 경로 등에 공통 사용
"""
from collections import deque
from sqlalchemy.orm import Session

from app.models.map import MapPOI, MapLine


def _build_graph(db: Session, map_id: int) -> tuple[dict[int, set[int]], dict[int, "MapPOI"]]:
    """맵의 POI/Line으로 양방향 인접 그래프 생성
    반환: (graph, poi_by_id)
    """
    pois = db.query(MapPOI).filter(
        MapPOI.map_id == map_id, MapPOI.is_active == True
    ).all()
    lines = db.query(MapLine).filter(
        MapLine.map_id == map_id, MapLine.is_active == True
    ).all()

    poi_by_id = {p.id: p for p in pois}
    graph: dict[int, set[int]] = {p.id: set() for p in pois}

    for line in lines:
        if line.from_poi_id in graph and line.to_poi_id in graph:
            # 양방향으로 처리 (로봇은 양방향 주행 가능)
            graph[line.from_poi_id].add(line.to_poi_id)
            graph[line.to_poi_id].add(line.from_poi_id)

    return graph, poi_by_id


def find_route(
    db: Session,
    map_id: int,
    from_poi_id: int,
    to_poi_id: int,
    include_endpoints: bool = False,
) -> list[str]:
    """두 POI 사이의 최단 경로를 BFS로 탐색
    반환: 경유 POI name 목록
    include_endpoints=False: 출발/도착 POI 제외 (경유점만)
    include_endpoints=True: 출발/도착 POI 포함
    """
    if from_poi_id == to_poi_id:
        return []

    graph, poi_by_id = _build_graph(db, map_id)

    if from_poi_id not in graph or to_poi_id not in graph:
        return []

    # BFS
    visited: dict[int, int | None] = {from_poi_id: None}
    queue = deque([from_poi_id])

    while queue:
        current = queue.popleft()
        if current == to_poi_id:
            break
        for neighbor in graph.get(current, set()):
            if neighbor not in visited:
                visited[neighbor] = current
                queue.append(neighbor)

    if to_poi_id not in visited:
        return []  # 도달 불가

    # 경로 복원: to → ... → from (역순)
    path_ids = []
    cur = to_poi_id
    while cur is not None:
        path_ids.append(cur)
        cur = visited.get(cur)
    path_ids.reverse()  # from → ... → to

    # POI name으로 변환
    if include_endpoints:
        return [poi_by_id[pid].name for pid in path_ids if pid in poi_by_id]
    else:
        # 출발/도착 제외
        return [poi_by_id[pid].name for pid in path_ids[1:-1] if pid in poi_by_id]


def find_route_by_name(
    db: Session,
    map_id: int,
    from_name: str,
    to_name: str,
    include_endpoints: bool = False,
) -> list[str]:
    """POI 이름으로 경로 탐색"""
    from_poi = db.query(MapPOI).filter(
        MapPOI.map_id == map_id, MapPOI.name == from_name, MapPOI.is_active == True
    ).first()
    to_poi = db.query(MapPOI).filter(
        MapPOI.map_id == map_id, MapPOI.name == to_name, MapPOI.is_active == True
    ).first()

    if not from_poi or not to_poi:
        return []

    return find_route(db, map_id, from_poi.id, to_poi.id, include_endpoints)


def find_charging_entry_route(db: Session, robot_id: int, first_work_name: str) -> list[str]:
    """로봇 충전소 → 첫 WORK POI 까지의 진입 경로
    반환: 경유 POI name 목록 (충전소/WORK1 제외)
    """
    from app.models.robot import Robot

    robot = db.query(Robot).filter(Robot.id == robot_id).first()
    if not robot or not robot.charging_id:
        return []

    charging_poi = db.query(MapPOI).filter(
        MapPOI.id == robot.charging_id, MapPOI.is_active == True
    ).first()
    if not charging_poi:
        return []

    return find_route(db, charging_poi.map_id, charging_poi.id,
                      _get_poi_id(db, charging_poi.map_id, first_work_name),
                      include_endpoints=False)


def find_charging_return_route(db: Session, robot_id: int, first_work_name: str) -> list[str]:
    """첫 WORK POI → 로봇 충전소까지의 복귀 경로
    반환: 경유 POI name 목록 (WORK1/충전소 제외)
    """
    from app.models.robot import Robot

    robot = db.query(Robot).filter(Robot.id == robot_id).first()
    if not robot or not robot.charging_id:
        return []

    charging_poi = db.query(MapPOI).filter(
        MapPOI.id == robot.charging_id, MapPOI.is_active == True
    ).first()
    if not charging_poi:
        return []

    return find_route(db, charging_poi.map_id,
                      _get_poi_id(db, charging_poi.map_id, first_work_name),
                      charging_poi.id,
                      include_endpoints=False)


def find_work_loop_order(db: Session, map_id: int) -> list[str]:
    """WORK% POI의 루프 순서를 MapLine 유향 그래프에서 자동 결정.

    WORK1에서 시작하여 forward 방향 간선(from_poi→to_poi)을 따라
    다음 WORK 노드를 BFS로 찾아가며 루프 전체의 순서를 반환한다.
    실패 시 이름 기반 자연 정렬로 폴백.
    """
    import re

    pois = db.query(MapPOI).filter(
        MapPOI.map_id == map_id, MapPOI.is_active == True
    ).all()
    lines = db.query(MapLine).filter(
        MapLine.map_id == map_id, MapLine.is_active == True
    ).all()

    poi_by_id = {p.id: p for p in pois}
    work_ids = {p.id for p in pois if p.name.startswith("WORK")}

    if not work_ids:
        return []

    # WORK1 찾기
    start_id = None
    for pid in work_ids:
        if poi_by_id[pid].name == "WORK1":
            start_id = pid
            break

    if not start_id:
        return _natural_sort_work_names([poi_by_id[pid].name for pid in work_ids])

    # Forward 방향 유향 그래프 (from_poi → to_poi)
    fwd: dict[int, set[int]] = {p.id: set() for p in pois}
    for line in lines:
        fid, tid = line.from_poi_id, line.to_poi_id
        if fid in fwd and tid in fwd:
            d = line.direction or "forward"
            if d in ("forward", "bidirectional"):
                fwd[fid].add(tid)
            if d in ("backward", "bidirectional"):
                fwd[tid].add(fid)

    # WORK1부터 forward BFS로 다음 WORK 노드를 순서대로 찾기
    ordered = [start_id]
    visited_work = {start_id}

    current = start_id
    while len(visited_work) < len(work_ids):
        bfs_visited = {current}
        queue = deque([current])
        found_id = None

        while queue and found_id is None:
            node = queue.popleft()
            for neighbor in fwd.get(node, set()):
                if neighbor in bfs_visited:
                    continue
                bfs_visited.add(neighbor)

                if neighbor in work_ids and neighbor not in visited_work:
                    found_id = neighbor
                    break

                # non-WORK 노드는 경유하여 계속 탐색
                queue.append(neighbor)

        if found_id is None:
            break

        ordered.append(found_id)
        visited_work.add(found_id)
        current = found_id

    if len(ordered) == len(work_ids):
        return [poi_by_id[pid].name for pid in ordered]

    # 그래프 탐색 실패 → 이름 자연 정렬 폴백
    return _natural_sort_work_names([poi_by_id[pid].name for pid in work_ids])


def _natural_sort_work_names(names: list[str]) -> list[str]:
    """WORK 이름 자연 정렬 (WORK1, WORK1-1, WORK2, ...)"""
    import re

    def key(name: str):
        return [int(c) if c.isdigit() else c.lower() for c in re.split(r"(\d+)", name)]

    return sorted(names, key=key)


def _get_poi_id(db: Session, map_id: int, name: str) -> int:
    """POI 이름으로 ID 조회"""
    poi = db.query(MapPOI).filter(
        MapPOI.map_id == map_id, MapPOI.name == name, MapPOI.is_active == True
    ).first()
    return poi.id if poi else -1
