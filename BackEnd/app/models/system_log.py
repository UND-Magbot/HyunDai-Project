from sqlalchemy import Column, Integer, String, DateTime, Text
from sqlalchemy.sql import func

from app.database import Base


class SystemLog(Base):
    """시스템 로그 테이블 — activity_logs와 동일한 구조"""
    __tablename__ = "system_logs"
    __table_args__ = {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"}

    id = Column(Integer, primary_key=True, autoincrement=True)
    category = Column(String(20), nullable=False, index=True)
    action = Column(String(50), nullable=False, index=True)
    message = Column(Text, nullable=False)
    detail = Column(Text, nullable=True)
    robot_id = Column(Integer, nullable=True, index=True)
    robot_name = Column(String(100), nullable=True)
    source = Column(String(100), nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False, index=True)
