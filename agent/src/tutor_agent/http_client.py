"""backend가 agent 서비스를 HTTP로 부르는 클라이언트 (`AgentProtocol` 구현).

`backend_adapter.TutorAgentAdapter`와 **같은 계약, 다른 전송 방식**이다.
어댑터는 파이프라인을 같은 프로세스에서 돌리고, 이 클라이언트는 별도
프로세스로 뜬 `service.py`에 HTTP로 물어본다.

왜 필요한가 (요약; 자세한 건 `service.py` 상단):
`strands-agents`가 끌어오는 `starlette 1.6.0`과 backend의
`fastapi 0.115.6`(`starlette<0.42.0`)이 **동시에 설치될 수 없다.** 그래서
파이프라인을 backend 프로세스 안에서 돌리는 길이 막혀 있다.

설계 원칙 (어댑터와 동일 + 네트워크 몫 추가)
--------------------------------------------
1. **strands를 import하지 않는다.** 이 모듈이 import하는 건 `httpx`와
   `backend_adapter`의 순수 데이터/헬퍼뿐이다. 그래서 backend venv에
   `strands-agents`를 설치하지 않아도(=설치하면 안 되는 상황에서도) 동작한다.
2. **절대 예외를 던지지 않는다.** 연결 거부/타임아웃/5xx/깨진 JSON/모르는
   action 값 — 전부 `AgentAction.WAIT`로 흘린다. 이 결정은 채점 응답과 같은
   트랜잭션에 실려 나가므로, 여기서 예외가 새면 agent 장애가 채점 결과까지
   깨뜨린다 (backend_plan §14).
3. **연결 타임아웃과 읽기 타임아웃을 분리한다.** 서비스가 아예 안 떠 있으면
   즉시(0.5초) 포기하고 WAIT, 실제로 LLM을 돌리는 중이면 끝까지 기다린다.
   둘을 한 값으로 묶으면 "서비스 꺼짐"에도 매 요청이 십수 초씩 매달린다.

알려진 한계
-----------
`decide()`는 **동기 호출**이다. 원래 파이프라인이 LLM을 4번 순차 호출해서
(state -> guidance -> action -> evaluation) 실측 28~30초가 걸렸는데, 두 가지를
고쳤다: guidance+action을 한 번의 호출로 합치고(`orchestrator.py`,
`agents/guided_action_agent.py`), evaluation은 응답 경로에서 빼서
`service.py`가 응답 후 `BackgroundTasks`로 돌린다. 지금은 **16~18초**
(state -> guided_action, 2번 순차 호출). 자세한 논의는 agent/README.md의
"지연 시간" 절 참고.

이 호출은 backend의 `POST /sessions/{id}/run|submit` 안에서 일어나므로,
Monitor가 트리거된 제출은 학생이 그만큼 기다리게 된다 — Monitor는 자주
트리거되지 않으므로(예: 같은 결과 3회 반복) 평범한 제출은 영향 없다.

더 줄이려면 state까지 합쳐서 LLM 호출을 1번으로 만들 수 있는데, "학생 상태
판단"과 "지도 방법 결정"이 하나의 프롬프트에 뭉쳐져 판단이 덜 세밀해질 수
있다. 근본적으로는 **"채점 결과는 즉시 반환하고, agent 결정은 별도 채널로
나중에 전달"**이 맞는데, backend 라우터와 frontend 수신부를 같이 고쳐야 해서
이 파일 혼자 정할 수 없다. `AGENT_SERVICE_TIMEOUT_SECONDS`를 낮추면 "느리면
그냥 WAIT"로 흘려보낼 수도 있다 — 개입을 포기하는 대신 응답 속도를 지키는 선택.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from .backend_adapter import (
    REPLY_FALLBACK_MESSAGE,
    AgentAction,
    AgentDecision,
    AgentReply,
    _fallback_reply,
    _field_of,
    _wait_decision,
)

log = logging.getLogger(__name__)

#: agent 서비스 주소. backend 프로세스의 환경변수로 덮어쓸 수 있다.
DEFAULT_BASE_URL = "http://localhost:8100"

#: LLM 파이프라인이 실제로 도는 시간. state -> guided_action 2개를 순차 호출한다.
#:
#: **로컬 실측 16~18초** (Anthropic 다이렉트 API, guidance+action 병합 이후 —
#: 병합 전엔 28~30초였다. 위 "알려진 한계" 참고). 처음엔 15초로 잡았다가 매번
#: ReadTimeout -> 항상 WAIT가 되는 걸 실제로 겪어서 실측 기반으로 잡았다.
#: 30초는 "실측 + 여유"이지 이상적인 값이 아니다 — 근본 해결은 비동기화다.
DEFAULT_READ_TIMEOUT_SECONDS = 30.0

#: 서비스가 안 떠 있는 경우를 빨리 포기하기 위한 값. 읽기 타임아웃과 분리한다.
DEFAULT_CONNECT_TIMEOUT_SECONDS = 0.5

#: backend `AgentContext`에서 서비스로 넘길 필드 (= 계약).
CONTEXT_FIELDS = (
    "session_id",
    "problem",
    "current_code",
    "current_code_version",
    "judge_result",
    "recent_trace",
    "features",
    "process_status",
    "trigger",
    "evidence",
    "previous_interventions",
)

WAIT_REASON_UNREACHABLE = (
    "Agent 서비스에 연결하지 못해 개입하지 않고 기다립니다."
)
WAIT_REASON_BAD_RESPONSE = (
    "Agent 서비스 응답을 해석하지 못해 개입하지 않고 기다립니다."
)


def _env_float(name: str, default: float) -> float:
    """환경변수를 float으로 읽되, 이상한 값이면 조용히 기본값을 쓴다.

    설정 오타 하나로 agent 연결이 통째로 죽는 것보다, 기본값으로 동작하면서
    경고를 남기는 편이 낫다.
    """
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        log.warning("%s=%r 를 숫자로 읽지 못해 기본값 %s를 씁니다.", name, raw, default)
        return default


def to_payload(ctx: Any) -> dict[str, Any]:
    """backend `AgentContext`(dataclass/pydantic/dict 무엇이든) -> JSON 본문.

    `_field_of`가 세 형태를 모두 처리하므로, backend가 표현 방식을 바꿔도
    여기는 안 깨진다.
    """
    return {name: _field_of(ctx, name) for name in CONTEXT_FIELDS}


class HttpAgentClient:
    """`AgentProtocol`을 만족하는 HTTP 클라이언트. 예외를 던지지 않는다.

    Args:
        base_url: agent 서비스 주소. None이면 `AGENT_SERVICE_URL` 환경변수,
            그것도 없으면 `DEFAULT_BASE_URL`.
        read_timeout / connect_timeout: None이면 각각
            `AGENT_SERVICE_TIMEOUT_SECONDS` / `AGENT_SERVICE_CONNECT_TIMEOUT_SECONDS`
            환경변수, 그것도 없으면 위의 기본 상수.
        client: 테스트에서 가짜 전송을 꽂기 위한 주입 지점.
    """

    #: backend가 로그/이벤트에 남기는 이름. in-process 어댑터("tutor_agent")와
    #: 구분되게 둔다 — 어느 경로로 붙었는지 로그만 보고 알 수 있어야 한다.
    name = "tutor_agent_http"

    def __init__(
        self,
        base_url: str | None = None,
        *,
        read_timeout: float | None = None,
        connect_timeout: float | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = (
            base_url or os.getenv("AGENT_SERVICE_URL") or DEFAULT_BASE_URL
        ).rstrip("/")
        self._read_timeout = (
            read_timeout
            if read_timeout is not None
            else _env_float("AGENT_SERVICE_TIMEOUT_SECONDS", DEFAULT_READ_TIMEOUT_SECONDS)
        )
        self._connect_timeout = (
            connect_timeout
            if connect_timeout is not None
            else _env_float(
                "AGENT_SERVICE_CONNECT_TIMEOUT_SECONDS", DEFAULT_CONNECT_TIMEOUT_SECONDS
            )
        )
        self._client = client

    def _get_client(self) -> httpx.Client:
        """연결을 재사용한다. 요청마다 새로 만들면 TCP/TLS 핸드셰이크가 매번 붙는다."""
        if self._client is None:
            self._client = httpx.Client(
                base_url=self.base_url,
                timeout=httpx.Timeout(
                    self._read_timeout, connect=self._connect_timeout
                ),
            )
        return self._client

    def decide(self, ctx: Any) -> AgentDecision:
        """backend가 부르는 단일 진입점. **어떤 경우에도 예외를 던지지 않는다.**"""
        try:
            payload = to_payload(ctx)
        except Exception:
            log.exception("AgentContext 직렬화 실패. WAIT로 폴백합니다.")
            return _wait_decision(ctx, WAIT_REASON_BAD_RESPONSE)

        try:
            response = self._get_client().post("/decide", json=payload)
            response.raise_for_status()
            body = response.json()
        except Exception:
            # 연결 거부 / 타임아웃 / 4xx / 5xx / JSON 아님 — 전부 여기로 모인다.
            log.warning(
                "Agent 서비스(%s) 호출 실패. WAIT로 폴백합니다.", self.base_url, exc_info=True
            )
            return _wait_decision(ctx, WAIT_REASON_UNREACHABLE)

        return self._to_decision(body, ctx)

    def _to_decision(self, body: Any, ctx: Any) -> AgentDecision:
        """서비스 응답 JSON -> backend `AgentDecision`.

        모르는 `action` 값은 WAIT로 떨어뜨린다. 서비스가 backend enum에 없는
        값을 보내면 backend가 나중에 `AgentAction(...)`으로 되돌릴 때 터지는데,
        그 폭발이 채점 트랜잭션 안에서 일어나기 때문이다.
        """
        try:
            if not isinstance(body, dict):
                raise TypeError(f"dict가 아닌 응답: {type(body).__name__}")
            action = AgentAction(str(body.get("action", "")))
            activity = body.get("activity")
            return AgentDecision(
                state=str(body.get("state", "") or ""),
                concept=body.get("concept"),
                action=action,
                reason=str(body.get("reason", "") or ""),
                activity=activity if isinstance(activity, dict) else None,
            )
        except Exception:
            log.warning("Agent 서비스 응답 해석 실패: %r", body, exc_info=True)
            return _wait_decision(ctx, WAIT_REASON_BAD_RESPONSE)

    def respond(self, ctx: Any, answer: str, question: str = "") -> AgentReply:
        """학생이 보낸 답변에 대한 튜터 응답을 받아온다. **예외를 던지지 않는다.**

        `decide()`가 실패하면 WAIT(침묵)으로 떨어지는 게 맞지만, 이 경로는
        학생이 직접 말을 건 상황이라 침묵하면 안 된다 — 실패해도 사람이 읽을
        수 있는 문구를 돌려준다 (`backend_adapter.REPLY_FALLBACK_MESSAGE`).
        """
        try:
            payload = to_payload(ctx)
            payload["answer"] = answer
            payload["question"] = question
        except Exception:
            log.exception("AgentContext 직렬화 실패 (학생 답변 경로).")
            return _fallback_reply(REPLY_FALLBACK_MESSAGE)

        try:
            response = self._get_client().post("/respond", json=payload)
            response.raise_for_status()
            body = response.json()
        except Exception:
            log.warning(
                "Agent 서비스(%s) /respond 호출 실패.", self.base_url, exc_info=True
            )
            return _fallback_reply(REPLY_FALLBACK_MESSAGE)

        if not isinstance(body, dict) or not str(body.get("message", "") or "").strip():
            log.warning("Agent 서비스 /respond 응답 해석 실패: %r", body)
            return _fallback_reply(REPLY_FALLBACK_MESSAGE)

        # 서비스가 필드를 빠뜨리거나 늘려도 안 깨지게, 아는 필드만 골라 담는다.
        return AgentReply(
            message=str(body["message"]),
            expects_reply=bool(body.get("expects_reply", False)),
            question=str(body.get("question", "") or ""),
            understanding=str(body.get("understanding", "") or ""),
            is_correct=bool(body.get("is_correct", False)),
            follow_up_needed=bool(body.get("follow_up_needed", True)),
            misconceptions=[str(m) for m in body.get("misconceptions") or []],
            evidence=str(body.get("evidence", "") or ""),
            next_focus=str(body.get("next_focus", "") or ""),
        )

    def is_available(self) -> bool:
        """`GET /health`로 서비스가 떠 있는지 확인한다 (진단/기동 로그용).

        backend의 `DockerJudge.is_available()`과 같은 역할이다. `decide()`는
        이걸 부르지 않는다 — 매 요청에 헬스체크를 얹으면 왕복이 두 배가 된다.
        """
        try:
            response = self._get_client().get(
                "/health", timeout=httpx.Timeout(2.0, connect=self._connect_timeout)
            )
            return response.status_code == 200
        except Exception:
            return False


def get_http_agent(base_url: str | None = None) -> HttpAgentClient:
    """`get_agent()`에서 한 줄로 쓰기 위한 팩토리.

    `backend_adapter.get_backend_agent()`와 달리 `lru_cache`를 걸지 않는다 —
    `HttpAgentClient`가 내부에 `httpx.Client`(연결 풀)를 들고 있어서, 캐시
    수명과 커넥션 수명이 엮이면 테스트에서 닫힌 커넥션을 재사용하는 사고가
    난다. 대신 호출부(`backend_entry.install`)에서 인스턴스를 한 번 만들어
    재사용한다.
    """
    return HttpAgentClient(base_url)
