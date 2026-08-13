"""`service.py`(agent HTTP 서비스) 테스트.

LLM은 부르지 않는다 — `TutorAgentAdapter`에 가짜 파이프라인을 주입해서
HTTP 계층(요청 파싱 / 응답 직렬화 / 실패 처리)만 검증한다.

핵심 계약: 이 서비스는 **5xx를 내지 않는다.** 파이프라인이 어떻게 실패하든
파싱 가능한 WAIT 결정을 돌려줘야 backend가 채점 응답을 지킬 수 있다.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from tutor_agent import service  # noqa: E402
from tutor_agent.backend_adapter import TutorAgentAdapter, get_backend_agent  # noqa: E402
from tutor_agent.orchestrator import PipelineResult  # noqa: E402
from tutor_agent.schemas import ActionPlan, GuidancePlan, StudentState  # noqa: E402

CONTEXT = {
    "session_id": "sess_1",
    "problem": {"problem_id": "p1", "title": "t", "concepts": ["loop"]},
    "current_code": "print(1)",
    "current_code_version": 3,
    "judge_result": {"status": "WRONG_ANSWER", "passed": 2, "total": 4},
    "recent_trace": ["RUN 2/4"],
    "features": {"attempt_count": 3},
    "process_status": "STUCK",
    "trigger": "REPEATED_FAILURE",
    "evidence": ["동일 결과 2/4 ×3"],
    "previous_interventions": [],
}


@pytest.fixture
def client(monkeypatch):
    """어댑터 싱글턴 캐시를 테스트마다 비운다 (`lru_cache`가 걸려 있다)."""
    get_backend_agent.cache_clear()
    yield TestClient(service.app)
    get_backend_agent.cache_clear()


def _wire_pipeline(monkeypatch, pipeline) -> None:
    monkeypatch.setattr(
        service, "get_backend_agent", lambda: TutorAgentAdapter(pipeline=pipeline)
    )


def test_health_reports_ok(client) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_decide_returns_a_hint_when_the_pipeline_intervenes(client, monkeypatch) -> None:
    pipeline = MagicMock()
    pipeline.run.return_value = PipelineResult(
        student_state=StudentState(
            state_summary="같은 오류를 반복하고 있습니다",
            should_intervene=True,
            urgency="high",
        ),
        guidance_plan=GuidancePlan(approach="직접 힌트", message_draft="인덱스를 확인해보세요"),
        action_plan=ActionPlan(action_type="send_message", payload={}),
    )
    _wire_pipeline(monkeypatch, pipeline)

    response = client.post("/decide", json=CONTEXT)

    assert response.status_code == 200
    body = response.json()
    assert body["action"] == "HINT"
    assert body["state"] == "STUCK"
    assert body["concept"] == "loop"
    assert body["activity"]["message"] == "인덱스를 확인해보세요"


def test_decide_returns_wait_when_the_pipeline_declines(client, monkeypatch) -> None:
    pipeline = MagicMock()
    pipeline.run.return_value = PipelineResult(
        student_state=StudentState(state_summary="순조롭습니다", should_intervene=False),
    )
    _wire_pipeline(monkeypatch, pipeline)

    body = client.post("/decide", json=CONTEXT).json()

    assert body["action"] == "WAIT"
    assert body["activity"] is None


def test_decide_returns_wait_instead_of_500_when_the_pipeline_explodes(
    client, monkeypatch
) -> None:
    """서비스는 5xx를 내지 않는다 — backend가 항상 파싱 가능한 결정을 받아야 한다."""
    pipeline = MagicMock()
    pipeline.run.side_effect = RuntimeError("LLM provider is down")
    _wire_pipeline(monkeypatch, pipeline)

    response = client.post("/decide", json=CONTEXT)

    assert response.status_code == 200
    assert response.json()["action"] == "WAIT"


def test_decide_tolerates_a_minimal_body(client, monkeypatch) -> None:
    """backend가 필드를 빠뜨려도 422로 죽지 않고 WAIT로 흘러야 한다."""
    pipeline = MagicMock()
    pipeline.run.side_effect = RuntimeError("boom")
    _wire_pipeline(monkeypatch, pipeline)

    response = client.post("/decide", json={})

    assert response.status_code == 200
    assert response.json()["action"] == "WAIT"


def test_decide_tolerates_unknown_extra_fields(client, monkeypatch) -> None:
    """backend가 AgentContext에 필드를 추가해도 이 서비스는 안 깨진다."""
    pipeline = MagicMock()
    pipeline.run.return_value = PipelineResult(
        student_state=StudentState(state_summary="", should_intervene=False),
    )
    _wire_pipeline(monkeypatch, pipeline)

    response = client.post("/decide", json={**CONTEXT, "brand_new_field": 42})

    assert response.status_code == 200


def test_generate_problem_returns_a_structured_failure_not_500(client, monkeypatch) -> None:
    """문제 생성이 터져도 500이 아니라 is_valid=False로 돌려준다."""
    import tutor_agent.agents.problem_generator_agent as generator

    monkeypatch.setattr(
        generator, "generate", MagicMock(side_effect=RuntimeError("no api key"))
    )

    response = client.post(
        "/generate-problem", json={"student_id": "s1", "concept": "loop"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["is_valid"] is False
    assert "no api key" in body["error_message"]


def test_generate_problem_passes_through_a_validated_problem(client, monkeypatch) -> None:
    import tutor_agent.agents.problem_generator_agent as generator
    from tutor_agent.schemas import ValidationReport

    monkeypatch.setattr(
        generator,
        "generate",
        MagicMock(
            return_value=ValidationReport(
                is_valid=True, problem_json={"title": "짝수 개수 세기"}
            )
        ),
    )

    body = client.post(
        "/generate-problem", json={"student_id": "s1", "concept": "loop"}
    ).json()

    assert body["is_valid"] is True
    assert body["problem_json"]["title"] == "짝수 개수 세기"
