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
import os
from typing import Any

log = logging.getLogger(__name__)

#: 어떤 전송 방식으로 파이프라인에 닿을지. `AGENT_WIRING` 환경변수로 바꾼다.
#:
#: * `"http"` (기본) — 별도 프로세스로 띄운 `service.py`에 HTTP로 물어본다.
#: * `"inprocess"` — `backend_adapter.TutorAgentAdapter`를 같은 프로세스에서 쓴다.
#:
#: **기본값이 http인 이유**: in-process는 backend venv에 `strands-agents`가
#: 있어야 하는데, 그게 끌어오는 `starlette 1.6.0`이 backend의
#: `fastapi 0.115.6`(`starlette<0.42.0`)과 충돌해서 **같이 설치될 수 없다**
#: (실제로 설치해서 backend가 깨지는 것까지 확인함). 설치하지 않으면 첫
#: `decide()`에서 `ModuleNotFoundError: No module named 'strands'`가 나고
#: 어댑터 폴백에 걸려 항상 WAIT만 나온다. 자세한 건 `service.py` 상단 참고.
#:
#: `inprocess`는 그 의존성 충돌이 해소되는 날을 위해 남겨둔다.
DEFAULT_WIRING = "http"


def install(app: Any, *, respect_setting: bool = False, wiring: str | None = None) -> Any:
    """이미 만들어진 FastAPI 앱의 `get_agent` 의존성을 tutor_agent로 치환한다.

    Args:
        app: backend가 만든 FastAPI 인스턴스.
        respect_setting: True면 backend 설정 `AGENT_BACKEND`가 `"llm"`일 때만
            치환한다. 기본값 False — 이 진입점을 쓴다는 것 자체가 이미
            "LLM 에이전트로 돌린다"는 의사표시라고 본다.
        wiring: `"http"` | `"inprocess"`. None이면 `AGENT_WIRING` 환경변수,
            그것도 없으면 `DEFAULT_WIRING`.

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

        mode = (wiring or os.getenv("AGENT_WIRING") or DEFAULT_WIRING).strip().lower()

        if mode == "inprocess":
            from .backend_adapter import get_backend_agent

            app.dependency_overrides[get_agent] = get_backend_agent
            log.info("tutor_agent.backend_adapter.TutorAgentAdapter를 get_agent에 연결했습니다.")
            return app

        if mode != "http":
            log.warning("알 수 없는 AGENT_WIRING=%r. http로 진행합니다.", mode)

        from .http_client import HttpAgentClient

        # 인스턴스를 여기서 한 번 만들어 재사용한다. get_agent는 요청마다 평가되는
        # Depends라, 매번 새로 만들면 httpx 연결 풀도 매번 새로 생긴다.
        client = HttpAgentClient()
        app.dependency_overrides[get_agent] = lambda: client
        log.info("tutor_agent 서비스(%s)를 get_agent에 연결했습니다.", client.base_url)
        if not client.is_available():
            # 치명적이지 않다 — 서비스가 나중에 떠도 되고, 그동안은 WAIT로 폴백한다.
            log.warning(
                "Agent 서비스(%s)가 아직 응답하지 않습니다. "
                "`python -m uvicorn tutor_agent.service:app --port 8100`으로 띄우세요. "
                "그때까지 개입 결정은 WAIT로 폴백합니다.",
                client.base_url,
            )
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
