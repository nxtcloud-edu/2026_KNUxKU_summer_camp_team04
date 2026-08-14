"""`POST /agent/respond` — 학생이 튜터에게 답을 보내는 경로.

`POST /agent/decide`가 "튜터가 먼저 말을 걸까?"를 묻는 경로라면 이쪽은 학생이
이미 말을 건 뒤다. 이 라우트가 하는 일은 셋이다:

1. 소유권 검사 (build_context가 학생 코드/trace를 통째로 담아 오므로 필수)
2. **튜터가 직전에 무엇을 물었는지를 서버가 직접 찾아** agent에 넘긴다
   (클라이언트가 보내는 값을 믿지 않는다)
3. 튜터의 답장을 `AGENT_INTERVENTION`으로 남긴다 (새 EventType 없이)

LLM은 부르지 않는다 — `FakeAgent`를 꽂아 배선만 검증한다.
"""
from __future__ import annotations

import pytest
from sqlmodel import select

from app.agent import get_agent
from app.agent.interface import AgentDecision, AgentReply
from app.agent.stub import AGENT_UNAVAILABLE_REPLY, FakeAgent, WaitAgent
from app.enums import AgentAction, EventType
from app.main import app
from app.models import Event

from tests.factories import TraceBuilder

WAIT = AgentDecision(state="STUCK", concept=None, action=AgentAction.WAIT, reason="대기")


@pytest.fixture(name="session_id")
def session_id_fixture(db, user):
    return TraceBuilder.start(db, user_id=user.id).session_id


def _wire(agent) -> None:
    app.dependency_overrides[get_agent] = lambda: agent


@pytest.fixture(autouse=True)
def _restore_agent_override():
    yield
    app.dependency_overrides[get_agent] = lambda: WaitAgent()


def _interventions(db, session_id: str) -> list[Event]:
    return list(
        db.exec(
            select(Event)
            .where(Event.session_id == session_id)
            .where(Event.type == EventType.AGENT_INTERVENTION)
            .order_by(Event.seq)  # type: ignore[arg-type]
        ).all()
    )


# --- 기본 경로 ----------------------------------------------------------------


def test_respond_returns_the_tutors_message(client, session_id) -> None:
    _wire(FakeAgent(WAIT, AgentReply(message="0으로 두면 어떻게 될까요?", expects_reply=True)))

    r = client.post("/agent/respond", json={"session_id": session_id, "answer": "0으로요"})

    assert r.status_code == 200
    body = r.json()
    assert body["message"] == "0으로 두면 어떻게 될까요?"
    assert body["expects_reply"] is True


def test_response_body_hides_the_internal_evaluation(client, session_id) -> None:
    """학생 브라우저로 이해도 판정을 내려보내지 않는다.

    "이해도: none"을 학생에게 보여줄 이유가 없고, 교육자 화면은 trace에서 읽는다.
    """
    _wire(
        FakeAgent(
            WAIT,
            AgentReply(
                message="좋아요, 다음 줄을 볼까요?",
                understanding="none",
                misconceptions=["초기화 위치를 오해"],
                evidence="학생이 반복문 안이라고 답했습니다.",
                next_focus="초기화 위치",
            ),
        )
    )

    body = client.post(
        "/agent/respond", json={"session_id": session_id, "answer": "반복문 안에서요"}
    ).json()

    assert set(body) == {"message", "expects_reply", "question"}
    assert "none" not in str(body)
    assert "초기화 위치를 오해" not in str(body)


# --- 질문은 서버가 찾는다 -----------------------------------------------------


def test_the_question_comes_from_the_server_not_the_client(client, db, session_id) -> None:
    """튜터가 직전에 던진 질문을 서버가 자기 개입 기록에서 읽어 agent에 넘긴다.

    클라이언트가 보내는 값을 믿으면 질문을 바꿔 보내 평가를 통과시킬 수 있다.
    """
    from app.trace import service as trace_service

    trace_service.record_agent_intervention(
        db,
        session_id,
        state="STUCK",
        concept="loop",
        action="HINT",
        reason="내부 근거",
        activity={"message": "count는 어떤 값으로 시작할까요?", "question": "count는 어떤 값으로 시작할까요?"},
        trigger=None,
    )
    agent = FakeAgent(WAIT, AgentReply(message="맞아요!"))
    _wire(agent)

    client.post(
        "/agent/respond",
        json={
            "session_id": session_id,
            "answer": "0으로요",
            # 클라이언트가 질문을 주장해도 무시된다 (스키마에 아예 없는 필드).
            "question": "1로 시작하는 게 맞나요?",
        },
    )

    answer, question = agent.replies[-1]
    assert answer == "0으로요"
    assert question == "count는 어떤 값으로 시작할까요?"


def test_no_recorded_question_is_passed_as_empty(client, session_id) -> None:
    """학생이 먼저 말을 건 경우 — 직전 질문이 없으면 빈 문자열로 넘긴다."""
    agent = FakeAgent(WAIT, AgentReply(message="무엇이 막히나요?"))
    _wire(agent)

    client.post(
        "/agent/respond", json={"session_id": session_id, "answer": "이거 왜 안 되나요?"}
    )

    assert agent.replies[-1] == ("이거 왜 안 되나요?", "")


def test_a_hint_without_a_question_does_not_leak_an_older_question(
    client, db, session_id
) -> None:
    """질문 없는 힌트가 마지막이면, 그보다 앞선 질문은 학생이 답하는 대상이 아니다."""
    from app.trace import service as trace_service

    for activity in (
        {"message": "count는 어떤 값으로 시작할까요?", "question": "count는 어떤 값으로 시작할까요?"},
        {"message": "3번째 줄을 다시 볼까요?", "question": ""},  # 질문 아님
    ):
        trace_service.record_agent_intervention(
            db,
            session_id,
            state="STUCK",
            concept="loop",
            action="HINT",
            reason="내부 근거",
            activity=activity,
            trigger=None,
        )
    agent = FakeAgent(WAIT, AgentReply(message="네, 봤어요."))
    _wire(agent)

    client.post("/agent/respond", json={"session_id": session_id, "answer": "봤어요"})

    assert agent.replies[-1][1] == ""


# --- trace 기록 ---------------------------------------------------------------


def test_the_exchange_is_recorded_as_an_agent_intervention(client, db, session_id) -> None:
    """새 EventType을 만들지 않는다 — 튜터의 답장은 실제로 개입이고, 타임라인이 이미 렌더한다.

    HINT_REQUEST로 남기면 `features.hint_count`가 올라가서 Monitor의 근거와
    R0 규칙이 학생의 대화 때문에 흔들린다.
    """
    _wire(
        FakeAgent(
            WAIT,
            AgentReply(
                message="그 줄은 어디에 있어야 할까요?",
                expects_reply=True,
                question="그 줄은 어디에 있어야 할까요?",
                understanding="partial",
                is_correct=True,
                misconceptions=["초기화 위치를 오해"],
                next_focus="초기화 위치",
            ),
        )
    )

    client.post("/agent/respond", json={"session_id": session_id, "answer": "0으로요"})

    rows = _interventions(db, session_id)
    assert len(rows) == 1
    payload = rows[0].payload
    assert payload["action"] == "HINT"
    activity = payload["activity"]
    assert activity["kind"] == "chat"
    assert activity["message"] == "그 줄은 어디에 있어야 할까요?"
    # 학생이 무엇에 답했는지 / 무엇이라고 답했는지가 남는다.
    assert activity["student_answer"] == "0으로요"
    # 내부 평가는 여기(교육자 화면이 읽는 곳)에만 남는다.
    assert activity["understanding"] == "partial"
    assert activity["misconceptions"] == ["초기화 위치를 오해"]
    assert activity["next_focus"] == "초기화 위치"


def test_a_recorded_question_is_reusable_by_the_next_turn(client, db, session_id) -> None:
    """대화가 이어진다: 이번 턴이 남긴 question을 다음 턴이 찾아 쓴다."""
    agent = FakeAgent(
        WAIT, AgentReply(message="어디에 있어야 할까요?", expects_reply=True, question="어디에 있어야 할까요?")
    )
    _wire(agent)

    client.post("/agent/respond", json={"session_id": session_id, "answer": "0으로요"})
    client.post("/agent/respond", json={"session_id": session_id, "answer": "반복문 앞에요"})

    assert agent.replies[0] == ("0으로요", "")  # 첫 턴엔 직전 질문이 없었다
    assert agent.replies[1] == ("반복문 앞에요", "어디에 있어야 할까요?")


def test_hint_count_is_not_inflated_by_chatting(client, db, session_id) -> None:
    """대화가 Monitor의 "힌트 요청 ×N" 근거를 오염시키면 안 된다."""
    from app.trace.monitor import evaluate

    _wire(FakeAgent(WAIT, AgentReply(message="네!")))

    before = evaluate(db, session_id).features.hint_count
    client.post("/agent/respond", json={"session_id": session_id, "answer": "0으로요"})
    after = evaluate(db, session_id).features.hint_count

    assert before == after == 0


# --- 인증 / 소유권 ------------------------------------------------------------


def test_respond_requires_auth_and_ownership(client, anon_client, db, user) -> None:
    """build_context()가 학생 코드와 trace를 통째로 담아 오므로 소유권 검사가 필수다."""
    from tests.test_auth_api import signup

    sid = TraceBuilder.start(db, user_id=user.id).session_id
    body = {"session_id": sid, "answer": "0으로요"}

    assert anon_client.post("/agent/respond", json=body).status_code == 401

    intruder = signup(anon_client, email="respondintruder@example.com").json()["access_token"]
    r = anon_client.post(
        "/agent/respond", json=body, headers={"Authorization": f"Bearer {intruder}"}
    )
    assert r.status_code in (403, 404)

    assert client.post("/agent/respond", json=body).status_code == 200


# --- 견고성 -------------------------------------------------------------------


def test_an_empty_answer_is_rejected_by_the_schema(client, session_id) -> None:
    """빈 답변으로 LLM을 부를 이유가 없다 (프롬프트 비용만 든다)."""
    r = client.post("/agent/respond", json={"session_id": session_id, "answer": ""})

    assert r.status_code == 422


def test_an_overlong_answer_is_rejected(client, session_id) -> None:
    """답변이 프롬프트에 그대로 실려 나가므로 길이 상한이 없으면 비용을 클라이언트가 정한다."""
    r = client.post(
        "/agent/respond", json={"session_id": session_id, "answer": "가" * 2001}
    )

    assert r.status_code == 422


def test_a_failing_agent_still_answers_the_student(client, db, session_id) -> None:
    """학생이 말을 걸었으면 500을 주지 않는다 — 침묵도, 에러 화면도 안 된다."""

    class ExplodingAgent:
        name = "exploding"

        def decide(self, ctx):
            return WAIT

        def respond(self, ctx, answer, question=""):
            raise RuntimeError("agent 서비스 다운")

    _wire(ExplodingAgent())

    r = client.post("/agent/respond", json={"session_id": session_id, "answer": "0으로요"})

    assert r.status_code == 200
    assert r.json()["message"].strip()
    # 실패한 턴은 개입으로 기록하지 않는다 (한 말이 없으므로).
    assert _interventions(db, session_id) == []


def test_an_agent_without_respond_falls_back_instead_of_500(client, session_id) -> None:
    """구버전 구현체가 꽂혀 있어도 학생 화면이 깨지지 않는다."""

    class LegacyAgent:
        name = "legacy"

        def decide(self, ctx):
            return WAIT

    _wire(LegacyAgent())

    r = client.post("/agent/respond", json={"session_id": session_id, "answer": "0으로요"})

    assert r.status_code == 200
    assert r.json()["message"] == AGENT_UNAVAILABLE_REPLY


def test_the_default_wait_agent_says_something(client, session_id) -> None:
    """Agent 미구성 환경(AGENT_BACKEND=none)에서도 학생 입력이 무응답으로 끝나지 않는다."""
    _wire(WaitAgent())

    body = client.post(
        "/agent/respond", json={"session_id": session_id, "answer": "0으로요"}
    ).json()

    assert body["message"] == AGENT_UNAVAILABLE_REPLY
    assert body["expects_reply"] is False
