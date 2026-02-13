from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base
import pymysql

# MariaDB 접속 정보
DB_USER = "root"
DB_PASSWORD = "1234"
DB_HOST = "localhost"
DB_PORT = 3306
DB_NAME = "rcs_db"

DATABASE_URL = f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}?charset=utf8mb4"

engine = create_engine(DATABASE_URL, echo=False, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def create_database_if_not_exists():
    """rcs_db 데이터베이스가 없으면 자동 생성"""
    conn = pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        charset="utf8mb4",
    )
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                f"CREATE DATABASE IF NOT EXISTS `{DB_NAME}` "
                f"CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
        conn.commit()
    finally:
        conn.close()


def init_db():
    """DB 생성 + 테이블 생성"""
    create_database_if_not_exists()
    Base.metadata.create_all(bind=engine)


def get_db():
    """FastAPI Dependency — 요청마다 세션 생성/반환"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
