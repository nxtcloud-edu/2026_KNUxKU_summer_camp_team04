"""`http_client.HttpAgentClient` 테스트.

실제 네트워크를 쓰지 않는다 — `httpx.MockTransport`로 서버를 흉내낸다.
핵심은 **"어떤 실패에도 예외를 던지지 않고 WAIT로 흘린다"**는 계약이다.
이게 깨지면 agent 장애가 backend의 채점 응답까지 깨뜨린다 (backend_plan §14).
"""

from __future__ import annotations

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


# --- generate_problem() -------------------------------------------------------
#
# `decide()`와 같은 원칙: 어떤 실패도 예외로 새지 않는다. 다만 폴백 모양이
# 다르다 -- WAIT 결정이 아니라 `{"is_valid": False, ...}` 리포트다.


def test_generate_problem_returns_the_service_report() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/generate-problem"
        return httpx.Response(
            200,
            json={
                "is_valid": True,
                "problem_json": {"title": "새 문제"},
                "error_message": None,
                "failed_categories": [],
            },
        )

    report = _client(handler).generate_problem({"student_id": "s1", "concept": "loop"})

    assert report["is_valid"] is True
    assert report["problem_json"]["title"] == "새 문제"


@pytest.mark.parametrize(
    "handler",
    [
        pytest.param(lambda r: httpx.Response(500), id="5xx"),
        pytest.param(lambda r: httpx.Response(422), id="4xx"),
        pytest.param(
            lambda r: httpx.Response(200, content=b"not json"), id="broken-json"
        ),
        pytest.param(
            lambda r: (_ for _ in ()).throw(httpx.ConnectError("refused")),
            id="connection-refused",
        ),
        pytest.param(
            lambda r: (_ for _ in ()).throw(httpx.ReadTimeout("too slow")),
            id="timeout",
        ),
    ],
)
def test_generate_problem_never_raises(handler) -> None:
    report = _client(handler).generate_problem({"student_id": "s1", "concept": "loop"})

    assert report["is_valid"] is False
    assert report["error_message"]


def test_generate_problem_rejects_non_dict_response() -> None:
    """리스트가 오면 호출자가 .get()을 부르다 터진다 -- 여기서 막는다."""
    report = _client(lambda r: httpx.Response(200, json=[1, 2, 3])).generate_problem({})

    assert report["is_valid"] is False


def test_generate_problem_timeout_is_separate_from_decide(monkeypatch) -> None:
    """생성은 LLM + 도커 실행이라 실측 ~25초다. decide()의 30초를 그대로 쓰면
    정상 동작이 타임아웃으로 죽는다."""
    from tutor_agent.http_client import (
        DEFAULT_GENERATE_TIMEOUT_SECONDS,
        DEFAULT_READ_TIMEOUT_SECONDS,
    )

    assert DEFAULT_GENERATE_TIMEOUT_SECONDS > DEFAULT_READ_TIMEOUT_SECONDS

    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["timeout"] = request.extensions.get("timeout", {}).get("read")
        return httpx.Response(200, json={"is_valid": True})

    monkeypatch.setenv("AGENT_GENERATE_TIMEOUT_SECONDS", "77")
    _client(handler).generate_problem({})

    assert seen["timeout"] == 77.0
