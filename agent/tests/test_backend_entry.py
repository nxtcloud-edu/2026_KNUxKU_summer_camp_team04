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


def test_install_overrides_get_agent_with_the_adapter(monkeypatch) -> None:
    get_agent = _fake_backend(monkeypatch)
    app = SimpleNamespace(dependency_overrides={})

    returned = backend_entry.install(app)

    assert returned is app
    # backend의 get_agent 함수 객체가 키다 — FastAPI Depends(get_agent)와 같은 객체.
    assert app.dependency_overrides[get_agent] is get_backend_agent
    assert app.dependency_overrides[get_agent]().name == "tutor_agent"


def test_install_can_respect_agent_backend_setting(monkeypatch) -> None:
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
