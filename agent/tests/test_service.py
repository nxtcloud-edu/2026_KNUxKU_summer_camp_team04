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
from tutor_agent.orchestrator import PipelineResult, ReplyResult  # noqa: E402
from tutor_agent.schemas import (  # noqa: E402
    ActionPlan,
    AnswerEvaluation,
    GuidancePlan,
    StudentState,
    TutorMessage,
)

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
        guidance_plan=GuidancePlan(approach="직접 힌트", focus="인덱스 범위"),
        action_plan=ActionPlan(action_type="send_message", payload={}),
        tutor_message=TutorMessage(message="인덱스를 확인해보세요"),
    )
    _wire_pipeline(monkeypatch, pipeline)

    response = client.post("/decide", json=CONTEXT)

    assert response.status_code == 200
    body = response.json()
    assert body["action"] == "HINT"
    assert body["state"] == "STUCK"
    assert body["concept"] == "loop"
    assert body["activity"]["message"] == "인덱스를 확인해보세요"
    # 학생 화면에 갈 문구에 내부 판단문이 섞여 있지 않다.
    assert "같은 오류를 반복하고 있습니다" not in body["activity"]["message"]


def test_decide_returns_wait_when_the_pipeline_declines(client, monkeypatch) -> None:
    pipeline = MagicMock()
    pipeline.run.return_value = PipelineResult(
        student_state=StudentState(state_summary="순조롭습니다", should_intervene=False),
    )
    _wire_pipeline(monkeypatch, pipeline)

    body = client.post("/decide", json=CONTEXT).json()

    assert body["action"] == "WAIT"
    assert body["activity"] is None


def test_decide_does_not_grade_its_own_intervention(client, monkeypatch) -> None:
    """회귀 방지: `/decide`는 evaluation을 부르지 않는다.

    예전에는 응답을 반환한 뒤 백그라운드로 "방금 내 개입이 적절했는지"를 스스로
    채점했다 (`score=0.85 notes=매우 적절한 개입...`). 평가 대상이 틀렸고
    (평가해야 할 것은 학생의 답변), 결과는 로그로만 남아 아무 동작도 바꾸지
    않았다. 지금 평가는 `/respond`에서만 일어나고, 거기서는 결과가 실제로 다음
    응답 문장을 바꾼다.
    """
    import tutor_agent.agents.evaluation_agent as evaluation_agent_module

    mock_evaluate = MagicMock()
    monkeypatch.setattr(evaluation_agent_module, "evaluate_answer", mock_evaluate)

    pipeline = MagicMock()
    pipeline.run.return_value = PipelineResult(
        student_state=StudentState(state_summary="같은 오류 반복", should_intervene=True),
        guidance_plan=GuidancePlan(approach="직접 힌트"),
        action_plan=ActionPlan(action_type="send_message", payload={}),
        tutor_message=TutorMessage(message="확인해보세요"),
    )
    _wire_pipeline(monkeypatch, pipeline)

    response = client.post("/decide", json=CONTEXT)

    assert response.json()["action"] == "HINT"
    mock_evaluate.assert_not_called()


# --- POST /respond (학생이 답을 보낸 경로) -----------------------------------


def _reply_result() -> ReplyResult:
    return ReplyResult(
        evaluation=AnswerEvaluation(
            understanding="partial",
            is_correct=False,
            misconceptions=["초기화 위치를 오해"],
            follow_up_needed=True,
            next_focus="초기화 위치",
        ),
        tutor_message=TutorMessage(
            message="0으로 두는 건 맞아요! 그 줄이 반복문 안에 있으면 어떻게 될까요?",
            question="그 줄이 반복문 안에 있으면 어떻게 될까요?",
            expects_reply=True,
        ),
    )


def test_respond_evaluates_the_student_answer_and_returns_a_message(
    client, monkeypatch
) -> None:
    pipeline = MagicMock()
    pipeline.respond_to_student.return_value = _reply_result()
    _wire_pipeline(monkeypatch, pipeline)

    response = client.post(
        "/respond",
        json={**CONTEXT, "answer": "0으로요. 반복문 안에서요.", "question": "언제 초기화해야 할까요?"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["message"].startswith("0으로 두는 건 맞아요")
    assert body["expects_reply"] is True
    assert body["understanding"] == "partial"
    assert body["misconceptions"] == ["초기화 위치를 오해"]

    # 질문과 답변이 파이프라인까지 실제로 전달됐다.
    _session_ctx, student_reply = pipeline.respond_to_student.call_args.args
    assert student_reply.answer == "0으로요. 반복문 안에서요."
    assert student_reply.question == "언제 초기화해야 할까요?"


def test_respond_never_returns_an_empty_message_when_the_pipeline_explodes(
    client, monkeypatch
) -> None:
    """학생이 말을 걸었으면 실패해도 말은 걸어준다 (WAIT=침묵으로 떨어지지 않는다)."""
    pipeline = MagicMock()
    pipeline.respond_to_student.side_effect = RuntimeError("LLM provider is down")
    _wire_pipeline(monkeypatch, pipeline)

    response = client.post("/respond", json={**CONTEXT, "answer": "모르겠어요"})

    assert response.status_code == 200
    assert response.json()["message"].strip()


def test_respond_tolerates_a_minimal_body(client, monkeypatch) -> None:
    pipeline = MagicMock()
    pipeline.respond_to_student.return_value = _reply_result()
    _wire_pipeline(monkeypatch, pipeline)

    response = client.post("/respond", json={"answer": "0으로요"})

    assert response.status_code == 200
    assert response.json()["message"]


def test_respond_rejects_nothing_but_still_answers_an_empty_body(client, monkeypatch) -> None:
    """answer가 비어도 422가 아니라 사람이 읽을 수 있는 문구로 돌려준다."""
    pipeline = MagicMock()
    _wire_pipeline(monkeypatch, pipeline)

    response = client.post("/respond", json={})

    assert response.status_code == 200
    assert response.json()["message"].strip()
    pipeline.respond_to_student.assert_not_called()


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
