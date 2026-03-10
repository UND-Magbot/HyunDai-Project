from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base
import pymysql

# MariaDB 접속 정보 (환경변수 우선, 없으면 기본값)
import os
DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "1234")
# DB_HOST = os.getenv("DB_HOST", "192.168.10.5")
DB_HOST = os.getenv("DB_HOST", "192.168.0.12")

DB_PORT = int(os.getenv("DB_PORT", "3306"))
DB_NAME = os.getenv("DB_NAME", "rcs_db")

DATABASE_URL = f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}?charset=utf8mb4"

engine = create_engine(
    DATABASE_URL, echo=False, pool_pre_ping=True,
    pool_size=10, max_overflow=20, pool_recycle=3600,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def create_database_if_not_exists():
    """rcs_db 데이터베이스가 없으면 자동 생성"""
    try:
        conn = pymysql.connect(
            host=DB_HOST,
            port=DB_PORT,
            user=DB_USER,
            password=DB_PASSWORD,
            charset="utf8mb4",
        )
    except Exception as e:
        print(f"[DB] 데이터베이스 서버 연결 실패 ({DB_HOST}:{DB_PORT}): {e}")
        raise

    try:
        with conn.cursor() as cursor:
            cursor.execute(
                f"CREATE DATABASE IF NOT EXISTS `{DB_NAME}` "
                f"CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
        conn.commit()
    except Exception as e:
        print(f"[DB] 데이터베이스 생성 실패 ({DB_NAME}): {e}")
        raise
    finally:
        conn.close()


def init_db():
    """DB 생성 + 테이블 생성 (스키마 변경된 테이블은 자동 재생성)"""
    try:
        create_database_if_not_exists()

        # convoy_configs 테이블 스키마 마이그레이션: robot_ids → robots_config
        from sqlalchemy import inspect as sa_inspect
        insp = sa_inspect(engine)
        if insp.has_table("convoy_configs"):
            columns = {c["name"] for c in insp.get_columns("convoy_configs")}
            if "robots_config" not in columns:
                with engine.begin() as conn:
                    conn.execute(text("DROP TABLE convoy_configs"))

        Base.metadata.create_all(bind=engine)

        # 메뉴 초기 데이터 시딩
        _seed_menus()
    except Exception as e:
        print(f"[DB] 데이터베이스 초기화 실패: {e}")
        raise


# 좌측 탭 메뉴 초기 데이터 (프론트엔드 SideNav와 일치)
_DEFAULT_MENUS = [
    {"menu_key": "monitoring", "menu_name": "모니터링", "sort_order": 1},
    {"menu_key": "robots",     "menu_name": "로봇관리",  "sort_order": 2},
    {"menu_key": "logs",       "menu_name": "로그관리",  "sort_order": 3},
    {"menu_key": "map",        "menu_name": "맵관리",    "sort_order": 4},
    {"menu_key": "settings",   "menu_name": "설정",      "sort_order": 5},
]

# 설정 하위 메뉴
_SETTINGS_CHILDREN = [
    {"menu_key": "settings.db_backup",       "menu_name": "DB 백업",      "sort_order": 1},
    {"menu_key": "settings.password_change", "menu_name": "비밀번호 변경", "sort_order": 2},
]


def _seed_menus():
    """menus 테이블 기본 데이터 시딩 (없는 항목만 추가)"""
    from app.models.menu import Menu

    db = SessionLocal()
    try:
        existing_keys = {m.menu_key for m in db.query(Menu.menu_key).all()}

        # 최상위 메뉴
        for item in _DEFAULT_MENUS:
            if item["menu_key"] not in existing_keys:
                db.add(Menu(**item))
        db.flush()

        # 설정 하위 메뉴
        settings = db.query(Menu).filter(Menu.menu_key == "settings").first()
        if settings:
            for item in _SETTINGS_CHILDREN:
                if item["menu_key"] not in existing_keys:
                    db.add(Menu(parent_id=settings.id, **item))

        db.commit()
        print("[DB] 기본 메뉴 데이터 시딩 완료")
    except Exception as e:
        db.rollback()
        print(f"[DB] 메뉴 시딩 실패: {e}")
    finally:
        db.close()


def get_db():
    """FastAPI Dependency — 요청마다 세션 생성/반환"""
    from fastapi import HTTPException
    db = SessionLocal()
    try:
        yield db
    except HTTPException:
        raise  # HTTP 예외는 DB 문제 아님 — 그냥 재전달
    except Exception as e:
        db.rollback()
        print(f"[DB] 세션 처리 중 오류 발생, 롤백 수행: {e}")
        raise
    finally:
        db.close()
