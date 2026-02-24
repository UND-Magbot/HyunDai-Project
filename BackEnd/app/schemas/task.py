from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime

# ─── 상태 매핑 ────────────────────────────────────────────────────────────────
TASK_STATUS_MAP = {0: "대기", 1: "실행중", 2: "완료", 3: "정지", 4: "에러"}


# ─── 웨이포인트 스키마 ──────────────────────────────────────────────────────────
class WaypointCreate(BaseModel):
    order: int = Field(..., ge=0, description="방문 순서 (0부터 시작)")
    name: Optional[str] = None
    x: float
    y: float
    orientation: float = 0.0
    wait_seconds: float = Field(default=0.0, ge=0)


class WaypointResponse(WaypointCreate):
    id: int

    class Config:
        from_attributes = True


# ─── 작업 스키마 ───────────────────────────────────────────────────────────────
class TaskCreate(BaseModel):
    name: str = Field(..., max_length=100)
    description: Optional[str] = None
    robot_id: int
    repeat_count: int = Field(default=-1, ge=-1, description="-1=무한반복, 0 이상=반복 횟수")
    waypoints: list[WaypointCreate] = Field(..., min_length=1)


class TaskUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=100)
    description: Optional[str] = None
    repeat_count: Optional[int] = Field(None, ge=-1)
    waypoints: Optional[list[WaypointCreate]] = None


class TaskResponse(BaseModel):
    id: int
    name: str
    description: Optional[str]
    robot_id: int
    repeat_count: int
    current_loop: int
    current_waypoint_order: int
    status: int
    status_name: str
    waypoints: list[WaypointResponse]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

    @classmethod
    def from_orm_with_status(cls, task):
        return cls(
            id=task.id,
            name=task.name,
            description=task.description,
            robot_id=task.robot_id,
            repeat_count=task.repeat_count,
            current_loop=task.current_loop,
            current_waypoint_order=task.current_waypoint_order,
            status=task.status,
            status_name=TASK_STATUS_MAP.get(task.status, "알 수 없음"),
            waypoints=task.waypoints,
            created_at=task.created_at,
            updated_at=task.updated_at,
        )


class TaskListResponse(BaseModel):
    total: int
    items: list[TaskResponse]


# ─── POI 스키마 (로봇 맵에서 조회) ────────────────────────────────────────────
class PoiResponse(BaseModel):
    id: str
    name: str
    x: float
    y: float
    orientation: float = 0.0
    poi_type: str = "unknown"
