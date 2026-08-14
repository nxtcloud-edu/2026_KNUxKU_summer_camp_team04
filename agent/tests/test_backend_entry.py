"""backend 무수정 진입점(`backend_entry.install`) 테스트.

backend를 실제로 import하지 않는다 — `app.agent` / `app.config`를 가짜 모듈로
sys.modules에 꽂아 넣어 override 배선만 검증한다. FastAPI도 필요 없다
(`dependency_overrides` dict를 가진 아무 객체나 받는다).
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from tutor_agent import backend_entry  # noqa: E402
from tutor_agent.backend_adapter import get_backend_agent  # noqa: E402


def _fake_backend(monkeypatch, *, agent_backend: str = "none"):
    """backend의 `app.agent.get_agent` / `app.config.get_settings`만 흉내낸다."""

    def get_agent() -> str:
        return "WaitAgent"

    app_pkg = ModuleType("app")
    app_agent = ModuleType("app.agent")
    app_agent.get_agent = get_agent  # type: ignore[attr-defined]
    app_config = ModuleType("app.config")
    app_config.get_settings = lambda: SimpleNamespace(  # type: ignore[attr-defined]
        agent_backend=agent_backend
    )
    monkeypatch.setitem(sys.modules, "app", app_pkg)
    monkeypatch.setitem(sys.modules, "app.agent", app_agent)
    monkeypatch.setitem(sys.modules, "app.config", app_config)
    return get_agent


def _silence_health_check(monkeypatch) -> None:
    """`install`의 기동 헬스체크가 테스트에서 실제 네트워크를 건드리지 않게 한다."""
    from tutor_agent.http_client import HttpAgentClient

    monkeypatch.setattr(HttpAgentClient, "is_available", lambda self: True)


def test_install_overrides_get_agent_with_the_http_client(monkeypatch) -> None:
    """기본 배선은 HTTP다 (in-process는 starlette 의존성 충돌로 쓸 수 없다 —
    `backend_entry.DEFAULT_WIRING` 주석 참고)."""
    get_agent = _fake_backend(monkeypatch)
    _silence_health_check(monkeypatch)
    app = SimpleNamespace(dependency_overrides={})

    returned = backend_entry.install(app)

    assert returned is app
    # backend의 get_agent 함수 객체가 키다 — FastAPI Depends(get_agent)와 같은 객체.
    assert app.dependency_overrides[get_agent]().name == "tutor_agent_http"


def test_install_reuses_one_client_across_requests(monkeypatch) -> None:
    """get_agent는 요청마다 평가되는 Depends다. 매번 새 클라이언트를 만들면
    httpx 연결 풀이 매번 새로 생긴다."""
    get_agent = _fake_backend(monkeypatch)
    _silence_health_check(monkeypatch)
    app = SimpleNamespace(dependency_overrides={})

    backend_entry.install(app)
    factory = app.dependency_overrides[get_agent]

    assert factory() is factory()


def test_install_can_still_wire_in_process(monkeypatch) -> None:
    """의존성 충돌이 해소되면 쓸 수 있도록 in-process 경로도 남아 있다."""
    get_agent = _fake_backend(monkeypatch)
    app = SimpleNamespace(dependency_overrides={})

    backend_entry.install(app, wiring="inprocess")

    assert app.dependency_overrides[get_agent] is get_backend_agent
    assert app.dependency_overrides[get_agent]().name == "tutor_agent"


def test_install_reads_wiring_from_env(monkeypatch) -> None:
    get_agent = _fake_backend(monkeypatch)
    monkeypatch.setenv("AGENT_WIRING", "inprocess")
    app = SimpleNamespace(dependency_overrides={})

    backend_entry.install(app)

    assert app.dependency_overrides[get_agent] is get_backend_agent


def test_install_can_respect_agent_backend_setting(monkeypatch) -> None:
    _silence_health_check(monkeypatch)
    get_agent = _fake_backend(monkeypatch, agent_backend="none")
    app = SimpleNamespace(dependency_overrides={})

    backend_entry.install(app, respect_setting=True)

    assert app.dependency_overrides == {}  # AGENT_BACKEND=none이면 손대지 않는다

    _fake_backend(monkeypatch, agent_backend="llm")
    app2 = SimpleNamespace(dependency_overrides={})
    backend_entry.install(app2, respect_setting=True)

    assert app2.dependency_overrides  # llm이면 치환한다


def test_install_never_breaks_app_startup(monkeypatch) -> None:
    """backend를 못 찾거나 override 대입이 실패해도 앱은 그대로 반환된다."""
    monkeypatch.setitem(sys.modules, "app", None)  # 'import app.agent'가 실패한다
    app = SimpleNamespace(dependency_overrides={})

    returned = backend_entry.install(app)

    assert returned is app
    assert app.dependency_overrides == {}


def test_module_import_does_not_require_backend() -> None:
    """`import tutor_agent.backend_entry`는 backend 없이도 성공해야 한다 (app은 lazy)."""
    assert callable(backend_entry.install)
    assert callable(backend_entry.create_app)
    assert "app" not in vars(backend_entry)  # 최상단에서 만들지 않는다 (PEP 562)
