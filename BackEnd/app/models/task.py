from sqlalchemy import Column, Integer, String, Boolean, Float, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class Task(Base):
    """작업 테이블
    status 코드: 0=대기, 1=실행중, 2=완료, 3=정지, 4=에러
    repeat_count: -1 = 무한반복, 0 이상 = 반복 횟수
    """
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    robot_id = Column(Integer, ForeignKey("robots.id", ondelete="CASCADE"), nullable=False, index=True)
    repeat_count = Column(Integer, default=-1)        # -1 = 무한반복
    current_loop = Column(Integer, default=0)         # 현재 반복 횟수
    current_waypoint_order = Column(Integer, default=0)  # 현재 실행 중인 웨이포인트 순서
    status = Column(Integer, default=0)               # 0=대기, 1=실행중, 2=완료, 3=정지, 4=에러
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    # 관계
    robot = relationship("Robot", backref="tasks")
    waypoints = relationship("TaskWaypoint", back_populates="task",
                             order_by="TaskWaypoint.order", cascade="all, delete-orphan")


class TaskWaypoint(Base):
    """작업 웨이포인트(노드) 테이블 — 순서대로 방문할 좌표 목록"""
    __tablename__ = "task_waypoints"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(Integer, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    order = Column(Integer, nullable=False)           # 방문 순서 (0부터 시작)
    name = Column(String(100), nullable=True)         # 노드 이름 (POI 이름)
    x = Column(Float, nullable=False)
    y = Column(Float, nullable=False)
    orientation = Column(Float, default=0.0)          # yaw (라디안)
    wait_seconds = Column(Float, default=0.0)         # 도착 후 대기 시간(초)

    # 관계
    task = relationship("Task", back_populates="waypoints")
