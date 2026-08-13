"""DB 엔진 / 세션 / 초기화."""
from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

from app.config import get_settings


@lru_cache
def get_engine() -> Engine:
    s = get_settings()
    return create_engine(
        s.database_url,
        # FastAPI는 async가 아닌 def 핸들러를 threadpool에서 돌린다.
        # 이게 없으면 "SQLite objects created in a thread can only be used in that
        # same thread"가 부하 상황에서만, 즉 데모 중에 간헐적으로 터진다.
        connect_args={"check_same_thread": False},
        echo=s.sql_echo,
    )


@event.listens_for(Engine, "connect")
def _sqlite_pragmas(dbapi_conn, _rec) -> None:  # type: ignore[no-untyped-def]
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")  # 읽기/쓰기 동시성
    cur.execute("PRAGMA busy_timeout=5000")  # 잠금은 에러가 아니라 대기로
    cur.execute("PRAGMA foreign_keys=ON")  # SQLite 기본값은 OFF다 (!)
    cur.close()


def init_db() -> None:
    # create_all은 클래스 정의 시점에 MetaData에 등록된 테이블만 만든다.
    # 이 import를 빼먹으면 테이블이 조용히 안 생긴다.
    import app.models  # noqa: F401

    SQLModel.metadata.create_all(get_engine())


def get_db() -> Iterator[Session]:
    """요청당 세션. commit은 서비스 계층에서 한다 (여기서 하면 실패가 롤백되지 않는다)."""
    with Session(get_engine()) as session:
        yield session


# NOTE: Alembic을 쓰지 않는다. create_all은 절대 ALTER하지 않는다.
#       모델을 바꿨으면 `rm codetrace.db` 후 재기동. README에 명시되어 있다.
