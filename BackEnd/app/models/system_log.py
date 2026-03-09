from sqlalchemy import Column, Integer, String, DateTime, Text
from sqlalchemy.sql import func

from app.database import Base


class SystemLog(Base):
    """시스템 로그 테이블 — 백엔드 콘솔 출력 자동 수집
    level: DEBUG | INFO | WARNING | ERROR | CRITICAL
    """
    __tablename__ = "system_logs"
    __table_args__ = {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"}

    id = Column(Integer, primary_key=True, autoincrement=True)
    level = Column(String(10), nullable=False, index=True)
    logger_name = Column(String(200), nullable=False, index=True)
    message = Column(Text, nullable=False)
    module = Column(String(100), nullable=True)
    func_name = Column(String(100), nullable=True)
    line_no = Column(Integer, nullable=True)
    exc_text = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
