"""backend 파일을 **한 줄도 고치지 않고** tutor_agent를 꽂는 대체 ASGI 진입점.

`backend/app/agent/__init__.py::get_agent()`는 지금 항상 `WaitAgent`를 반환한다
(`AGENT_BACKEND` 값은 경고 로그만 바꾼다). 그 파일을 수정하는 게 정공법이지만,
수정 권한/순서 문제로 지금 당장 못 고칠 때는 FastAPI의 `dependency_overrides`로
같은 결과를 낼 수 있다 — backend 소스가 아니라 **실행 대상 모듈만** 바꾸는 방식이다.

    cd backend
    PYTHONPATH=../agent/src uvicorn tutor_agent.backend_entry:app --reload
    # (agent를 backend venv에 pip install -e ../agent 했다면 PYTHONPATH 불필요)

`app.main:app` 대신 이 모듈의 `app`을 띄우면 라우터/미들웨어/DB는 backend가 만든
그대로이고, `Depends(get_agent)`만 `TutorAgentAdapter`로 치환된다.

주의점 (이래서 최종적으로는 backend 쪽 한 줄이 더 깔끔하다):

* `uvicorn app.main:app`으로 띄우는 사람(다른 팀원, Docker CMD, 배포 스크립트)은
  이 override를 못 받고 조용히 `WaitAgent`로 돌아간다. 실행 명령이 계약이 되는 셈.
* `dependency_overrides`는 원래 테스트용으로 문서화된 API다. 동작은 완전히
  동일하지만, "프로덕션 배선을 테스트용 훅으로 한다"는 냄새가 남는다.
* `AGENT_BACKEND` 값과 무관하게 무조건 override한다 (아래 `respect_setting=True`로
  바꾸면 설정을 따른다). `/health`의 `agent_backend` 값은 backend 설정을 그대로
  보여주므로, 이 진입점으로 띄운 사실은 로그로만 확인된다.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


def install(app: Any, *, respect_setting: bool = False) -> Any:
    """이미 만들어진 FastAPI 앱의 `get_agent` 의존성을 어댑터로 치환한다.

    Args:
        app: backend가 만든 FastAPI 인스턴스.
        respect_setting: True면 backend 설정 `AGENT_BACKEND`가 `"llm"`일 때만
            치환한다. 기본값 False — 이 진입점을 쓴다는 것 자체가 이미
            "LLM 에이전트로 돌린다"는 의사표시라고 본다.

    Returns:
        같은 `app` 객체 (치환에 실패해도 앱은 그대로 반환한다 — 기동을 막지 않는다).
    """
    try:
        from app.agent import get_agent  # backend 소속. 읽기만 한다.
        from app.config import get_settings

        if respect_setting and get_settings().agent_backend != "llm":
            log.warning(
                "AGENT_BACKEND=%s 이므로 tutor_agent를 꽂지 않습니다 (WaitAgent 유지).",
                get_settings().agent_backend,
            )
            return app

        from .backend_adapter import get_backend_agent

        app.dependency_overrides[get_agent] = get_backend_agent
        log.info("tutor_agent.backend_adapter.TutorAgentAdapter를 get_agent에 연결했습니다.")
    except Exception:
        # 여기서 던지면 backend가 아예 기동하지 못한다. Agent 없이라도 떠야 한다.
        log.exception("tutor_agent 연결 실패. backend는 WaitAgent로 계속 동작합니다.")
    return app


def create_app() -> Any:
    """backend 앱을 가져와 override를 적용한 ASGI 앱을 반환한다."""
    from app.main import app as backend_app

    return install(backend_app)


def __getattr__(name: str) -> Any:
    """`tutor_agent.backend_entry:app`을 **접근 시점에** 만든다 (PEP 562).

    모듈 최상단에서 `app = create_app()`을 하면 `import tutor_agent.backend_entry`
    자체가 backend(`app.main`)를 필요로 해서, backend 없이 이 모듈을 테스트하거나
    import할 수 없다. uvicorn은 `module:app`을 getattr로 찾으므로 아래로 충분하다.
    """
    if name == "app":
        return create_app()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
