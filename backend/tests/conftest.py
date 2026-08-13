from __future__ import annotations

from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.agent import get_agent
from app.agent.stub import WaitAgent
from app.auth.security import create_access_token
from app.db import get_db
from app.judge import get_judge
from app.judge.stub import UnavailableJudge
from app.main import app
from app.models import User

T0 = datetime(2026, 8, 13, 12, 0, 0)


@pytest.fixture(name="engine")
def engine_fixture():
    engine = create_engine(
        "sqlite://",  # in-memory
        connect_args={"check_same_thread": False},
        # StaticPool은 **필수**다. 없으면 SQLAlchemy가 커넥션마다 새 in-memory DB를 주고,
        # create_all은 한쪽에서 돌고 쿼리는 다른 쪽에서 돈다.
        # 증상은 명백히 맞아 보이는 테스트에서 나는 "no such table: sessions"다.
        # FastAPI + SQLite 테스트의 대표적 함정.
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture(name="db")
def db_fixture(engine):
    with Session(engine) as session:
        yield session


@pytest.fixture(name="user")
def user_fixture(db):
    """테스트용 회원 하나.

    세션이 users.id FK를 갖게 되면서 모든 trace 테스트가 실제 회원을 필요로 한다.
    비밀번호 해싱은 bcrypt라 느리므로 여기서는 해시를 직접 박아 넣는다 --
    인증 로직 자체는 test_auth_api.py가 검증한다.
    """
    u = User(
        email="tester@example.com",
        password_hash="$2b$12$" + "x" * 53,  # 로그인에 쓰지 않는 더미
        name="테스터",
        nickname="테스터",
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture(name="auth_headers")
def auth_headers_fixture(user):
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


@pytest.fixture(name="client")
def client_fixture(db, auth_headers):
    """인증된 클라이언트.

    거의 모든 엔드포인트가 로그인을 요구하므로 기본 헤더로 토큰을 달아둔다.
    인증 자체를 검증하는 테스트는 anon_client를 쓴다.
    """
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_judge] = lambda: UnavailableJudge()
    app.dependency_overrides[get_agent] = lambda: WaitAgent()
    # TestClient는 반드시 컨텍스트 매니저로 써야 lifespan이 돈다.
    with TestClient(app) as c:
        c.headers.update(auth_headers)
        yield c
    app.dependency_overrides.clear()


@pytest.fixture(name="anon_client")
def anon_client_fixture(db):
    """토큰 없는 클라이언트. 401 검증용."""
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_judge] = lambda: UnavailableJudge()
    app.dependency_overrides[get_agent] = lambda: WaitAgent()
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def frozen_now(monkeypatch):
    """app.clock.utcnow 하나만 패치한다.

    함수 하나, 장소 하나라서 모든 코드 경로에 적용되고 프로덕션 표면이 없다.
    순수 feature/monitor 테스트는 now=를 직접 넘기므로 이게 필요 없다.
    """
    holder = {"t": T0}
    monkeypatch.setattr("app.clock.utcnow", lambda: holder["t"])
    return holder
