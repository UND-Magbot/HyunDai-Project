from sqlalchemy.orm import Session
from fastapi import HTTPException

from app.models.task import Task, TaskWaypoint
from app.schemas.task import TaskCreate, TaskUpdate, TaskResponse, TaskListResponse


def _to_response(task: Task) -> TaskResponse:
    return TaskResponse.from_orm_with_status(task)


def create_task(db: Session, data: TaskCreate) -> TaskResponse:
    # 웨이포인트 order 중복 검사
    orders = [w.order for w in data.waypoints]
    if len(orders) != len(set(orders)):
        raise HTTPException(status_code=400, detail="웨이포인트 order 값이 중복됩니다.")

    task = Task(
        name=data.name,
        description=data.description,
        robot_id=data.robot_id,
        repeat_count=data.repeat_count,
    )
    db.add(task)
    db.flush()  # task.id 확보

    for wp_data in data.waypoints:
        wp = TaskWaypoint(
            task_id=task.id,
            order=wp_data.order,
            name=wp_data.name,
            x=wp_data.x,
            y=wp_data.y,
            orientation=wp_data.orientation,
            wait_seconds=wp_data.wait_seconds,
        )
        db.add(wp)

    db.commit()
    db.refresh(task)
    return _to_response(task)


def get_task(db: Session, task_id: int) -> TaskResponse:
    task = db.query(Task).filter(Task.id == task_id, Task.is_active == True).first()
    if not task:
        raise HTTPException(status_code=404, detail="작업을 찾지 못했습니다.")
    return _to_response(task)


def get_tasks(db: Session, robot_id: int = None, skip: int = 0, limit: int = 100) -> TaskListResponse:
    q = db.query(Task).filter(Task.is_active == True)
    if robot_id is not None:
        q = q.filter(Task.robot_id == robot_id)
    total = q.count()
    items = q.order_by(Task.created_at.desc()).offset(skip).limit(limit).all()
    return TaskListResponse(total=total, items=[_to_response(t) for t in items])


def update_task(db: Session, task_id: int, data: TaskUpdate) -> TaskResponse:
    task = db.query(Task).filter(Task.id == task_id, Task.is_active == True).first()
    if not task:
        raise HTTPException(status_code=404, detail="작업을 찾지 못했습니다.")
    if task.status == 1:
        raise HTTPException(status_code=400, detail="실행 중인 작업의 수정이 거부되었습니다.")

    if data.name is not None:
        task.name = data.name
    if data.description is not None:
        task.description = data.description
    if data.repeat_count is not None:
        task.repeat_count = data.repeat_count

    if data.waypoints is not None:
        orders = [w.order for w in data.waypoints]
        if len(orders) != len(set(orders)):
            raise HTTPException(status_code=400, detail="웨이포인트 order 값이 중복됩니다.")

        # 기존 웨이포인트 삭제 후 재생성
        db.query(TaskWaypoint).filter(TaskWaypoint.task_id == task_id).delete()
        for wp_data in data.waypoints:
            db.add(TaskWaypoint(
                task_id=task_id,
                order=wp_data.order,
                name=wp_data.name,
                x=wp_data.x,
                y=wp_data.y,
                orientation=wp_data.orientation,
                wait_seconds=wp_data.wait_seconds,
            ))

    db.commit()
    db.refresh(task)
    return _to_response(task)


def delete_task(db: Session, task_id: int) -> dict:
    task = db.query(Task).filter(Task.id == task_id, Task.is_active == True).first()
    if not task:
        raise HTTPException(status_code=404, detail="작업을 찾지 못했습니다.")
    if task.status == 1:
        raise HTTPException(status_code=400, detail="실행 중인 작업의 삭제가 거부되었습니다.")

    task.is_active = False
    db.commit()
    return {"message": f"작업 '{task.name}'이 삭제되었습니다"}
