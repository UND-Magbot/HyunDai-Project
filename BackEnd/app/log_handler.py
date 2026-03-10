import logging
import threading

from app.database import SessionLocal
from app.models.system_log import SystemLog


class DBLogHandler(logging.Handler):
    """Python 로깅 → DB 자동 저장 핸들러.

    루트 로거에 추가하면 uvicorn, FastAPI, 앱 코드 등
    모든 Python 로그가 system_logs 테이블에 자동 INSERT됨.

    안전 장치:
      - _local.is_writing: 스레드별 재귀 방지
      - SKIP_LOGGERS: DB 엔진 로그 제외 (무한루프 방지)
      - 실패 시 서버 동작에 영향 없음
    """

    SKIP_LOGGERS = frozenset({
        "sqlalchemy",
        "pymysql",
        "app.log_handler",
    })

    def __init__(self):
        super().__init__()
        self._local = threading.local()

    def emit(self, record: logging.LogRecord):
        # 재귀 방지
        if getattr(self._local, "is_writing", False):
            return

        # DB 엔진·커넥션 풀 로그 스킵
        for skip in self.SKIP_LOGGERS:
            if record.name.startswith(skip):
                return

        self._local.is_writing = True
        try:
            db = SessionLocal()
            try:
                log = SystemLog(
                    category="system",
                    action=record.levelname.lower(),
                    message=(self.format(record) if self.formatter else record.getMessage())[:500],
                    detail=self._format_exception(record),
                    source=f"{record.name} ({record.module}:{record.lineno})",
                )
                db.add(log)
                db.commit()
            except Exception:
                db.rollback()
            finally:
                db.close()
        except Exception:
            pass
        finally:
            self._local.is_writing = False

    @staticmethod
    def _format_exception(record: logging.LogRecord) -> str | None:
        if record.exc_info and record.exc_info[1]:
            import traceback
            return "".join(traceback.format_exception(*record.exc_info))
        if record.exc_text:
            return record.exc_text
        return None
