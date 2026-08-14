"""`http_client.HttpAgentClient` 테스트.

실제 네트워크를 쓰지 않는다 — `httpx.MockTransport`로 서버를 흉내낸다.
핵심은 **"어떤 실패에도 예외를 던지지 않고 WAIT로 흘린다"**는 계약이다.
이게 깨지면 agent 장애가 backend의 채점 응답까지 깨뜨린다 (backend_plan §14).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from tutor_agent.backend_adapter import AgentAction, AgentContext  # noqa: E402
from tutor_agent.http_client import HttpAgentClient, to_payload  # noqa: E402


def _ctx(**overrides) -> AgentContext:
    defaults = dict(
        session_id="sess_1",
        problem={"problem_id": "p1", "title": "t", "concepts": ["loop"]},
        current_code="print(1)",
        current_code_version=3,
        judge_result={"status": "WRONG_ANSWER", "passed": 2, "total": 4},
        recent_trace=["RUN 2/4"],
        features={"attempt_count": 3},
        process_status="STUCK",
        trigger="REPEATED_FAILURE",
        evidence=["동일 결과 2/4 ×3"],
    )
    defaults.update(overrides)
    return AgentContext(**defaults)


def _client(handler) -> HttpAgentClient:
    transport = httpx.MockTransport(handler)
    return HttpAgentClient(
        "http://agent.test",
        client=httpx.Client(transport=transport, base_url="http://agent.test"),
    )


def test_happy_path_returns_service_decision() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/decide"
        return httpx.Response(
            200,
            json={
                "state": "STUCK",
                "concept": "loop",
                "action": "HINT",
                "reason": "학생이 막혀 있습니다.",
                "activity": {"kind": "hint", "message": "인덱스를 확인해보세요"},
            },
        )

    decision = _client(handler).decide(_ctx())

    assert decision.action is AgentAction.HINT
    assert decision.state == "STUCK"
    assert decision.concept == "loop"
    assert decision.activity == {"kind": "hint", "message": "인덱스를 확인해보세요"}


def test_context_is_sent_with_the_agreed_field_names() -> None:
    """필드명이 backend 계약과 한 글자라도 다르면 서비스가 빈 컨텍스트로 판단한다."""
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"state": "", "action": "WAIT", "reason": ""})

    _client(handler).decide(_ctx())

    assert seen["session_id"] == "sess_1"
    assert seen["process_status"] == "STUCK"
    assert seen["trigger"] == "REPEATED_FAILURE"
    assert seen["problem"]["concepts"] == ["loop"]
    assert seen["judge_result"]["passed"] == 2
    assert seen["features"]["attempt_count"] == 3
    assert seen["previous_interventions"] == []


@pytest.mark.parametrize(
    "handler",
    [
        pytest.param(
            lambda request: (_ for _ in ()).throw(httpx.ConnectError("refused")),
            id="connection_refused",
        ),
        pytest.param(
            lambda request: (_ for _ in ()).throw(httpx.ReadTimeout("too slow")),
            id="read_timeout",
        ),
        pytest.param(lambda request: httpx.Response(500), id="server_error"),
        pytest.param(lambda request: httpx.Response(404), id="not_found"),
        pytest.param(
            lambda request: httpx.Response(200, content=b"not json"), id="broken_json"
        ),
        pytest.param(lambda request: httpx.Response(200, json=[1, 2]), id="not_an_object"),
        pytest.param(
            lambda request: httpx.Response(200, json={"action": "TELEPORT"}),
            id="unknown_action",
        ),
        pytest.param(lambda request: httpx.Response(200, json={}), id="empty_object"),
    ],
)
def test_every_failure_mode_falls_back_to_wait(handler) -> None:
    """연결 거부/타임아웃/5xx/깨진 JSON/모르는 action — 전부 WAIT, 예외 없음."""
    decision = _client(handler).decide(_ctx())

    assert decision.action is AgentAction.WAIT
    assert decision.reason  # 왜 WAIT인지 사람이 읽을 수 있어야 한다


def test_wait_fallback_still_carries_state_and_concept() -> None:
    """폴백이어도 backend가 기록할 state/concept은 컨텍스트에서 채워준다."""
    decision = _client(
        lambda request: (_ for _ in ()).throw(httpx.ConnectError("refused"))
    ).decide(_ctx())

    assert decision.state == "STUCK"
    assert decision.concept == "loop"


def test_decide_accepts_a_plain_dict_context() -> None:
    """backend가 dataclass 대신 dict를 넘겨도 동작한다 (duck typing)."""
    decision = _client(
        lambda request: httpx.Response(
            200, json={"state": "s", "action": "WAIT", "reason": "r"}
        )
    ).decide({"session_id": "sess_9", "process_status": "s"})

    assert decision.action is AgentAction.WAIT


def test_to_payload_covers_every_context_field() -> None:
    """계약 필드가 하나라도 빠지면 서비스 쪽에서 조용히 기본값으로 판단하게 된다."""
    payload = to_payload(_ctx())

    assert set(payload) == {
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
    }


def test_is_available_reports_service_health() -> None:
    assert _client(lambda request: httpx.Response(200)).is_available() is True
    assert _client(lambda request: httpx.Response(503)).is_available() is False
    assert (
        _client(
            lambda request: (_ for _ in ()).throw(httpx.ConnectError("refused"))
        ).is_available()
        is False
    )


def test_base_url_and_timeouts_come_from_env(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_SERVICE_URL", "http://elsewhere:9999/")
    monkeypatch.setenv("AGENT_SERVICE_TIMEOUT_SECONDS", "3.5")

    client = HttpAgentClient()

    assert client.base_url == "http://elsewhere:9999"  # 끝의 / 는 떼어낸다
    assert client._read_timeout == 3.5


def test_bad_timeout_env_falls_back_to_default(monkeypatch) -> None:
    """설정 오타 하나로 agent 연결이 통째로 죽으면 안 된다."""
    monkeypatch.setenv("AGENT_SERVICE_TIMEOUT_SECONDS", "빠르게")

    from tutor_agent.http_client import DEFAULT_READ_TIMEOUT_SECONDS

    assert HttpAgentClient()._read_timeout == DEFAULT_READ_TIMEOUT_SECONDS


# --- respond() (학생이 답을 보낸 경로) ---------------------------------------
#
# `decide()`와 계약이 하나 다르다: **침묵으로 폴백하지 않는다.** 학생이 직접
# 입력창에 뭔가를 써서 보낸 상황이라, WAIT(=아무 말 없음)로 떨어지면 "튜터가 내
# 말을 씹었다"가 된다. 그래서 모든 실패 모드에서 사람이 읽을 수 있는 문구가
# 담긴 AgentReply를 돌려줘야 한다.


def test_respond_happy_path_returns_message_and_evaluation() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/respond"
        body = json.loads(request.content)
        # 답변과 질문이 컨텍스트와 함께 실려 나간다.
        assert body["answer"] == "0으로요"
        assert body["question"] == "언제 초기화해야 할까요?"
        assert body["session_id"] == "sess_1"
        return httpx.Response(
            200,
            json={
                "message": "맞아요! 그 줄은 어디에 있어야 할까요?",
                "expects_reply": True,
                "question": "그 줄은 어디에 있어야 할까요?",
                "understanding": "partial",
                "is_correct": True,
                "follow_up_needed": True,
                "misconceptions": ["초기화 위치를 오해"],
                "evidence": "초기값은 맞혔습니다.",
                "next_focus": "초기화 위치",
            },
        )

    reply = _client(handler).respond(_ctx(), answer="0으로요", question="언제 초기화해야 할까요?")

    assert reply.message == "맞아요! 그 줄은 어디에 있어야 할까요?"
    assert reply.expects_reply is True
    assert reply.understanding == "partial"
    assert reply.misconceptions == ["초기화 위치를 오해"]
    assert reply.next_focus == "초기화 위치"


@pytest.mark.parametrize(
    "handler",
    [
        pytest.param(lambda request: httpx.Response(500, text="boom"), id="5xx"),
        pytest.param(lambda request: httpx.Response(200, text="JSON이 아님"), id="not-json"),
        pytest.param(lambda request: httpx.Response(200, json=["리스트"]), id="not-a-dict"),
        pytest.param(lambda request: httpx.Response(200, json={}), id="no-message"),
        pytest.param(lambda request: httpx.Response(200, json={"message": "   "}), id="blank-message"),
    ],
)
def test_respond_always_returns_a_readable_message(handler) -> None:
    reply = _client(handler).respond(_ctx(), answer="모르겠어요")

    assert reply.message.strip(), "학생이 말을 걸었는데 빈 응답을 돌려줬다"
    assert reply.understanding == ""  # 판정하지 못했음을 빈 값으로 표현


def test_respond_survives_a_dead_service() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("연결 거부", request=request)

    reply = _client(handler).respond(_ctx(), answer="모르겠어요")

    assert reply.message.strip()


def test_respond_ignores_unknown_extra_fields() -> None:
    """서비스가 필드를 늘려도 backend가 깨지지 않는다 (아는 필드만 골라 담는다)."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"message": "좋아요", "미래에_추가된_필드": 42})

    reply = _client(handler).respond(_ctx(), answer="0으로요")

    assert reply.message == "좋아요"
    assert reply.follow_up_needed is True  # 빠진 필드는 기본값
