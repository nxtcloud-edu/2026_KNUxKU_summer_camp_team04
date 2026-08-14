"""Agent Context Builder (backend_plan §13).

**지금 만든다.** LLM은 안 부르지만 이건 순수 trace 코드다.
모델 없이 테스트 가능하고, agent 개발자가 day 1에 필요로 하며,
무엇보다 **trace 데이터가 실제로 충분한지를 오늘 증명한다** -- 그게 이 프로젝트의 논지다.
build_context()가 못 채우는 필드가 있다면 그건 내일 새벽 2시가 아니라 지금 발견되는 누락이다.
"""
from __future__ import annotations

from datetime import datetime

from sqlmodel import Session as DbSession

from app.agent.interface import AgentContext
from app.enums import EventType
from app.problems.service import ProblemRepository
from app.sessions import store
from app.trace import service as trace_service
from app.trace.monitor import ProcessState, evaluate, features_to_dict
from app.trace.timeline import recent_trace_labels

RECENT_TRACE_LIMIT = 10


def _first_prose_line(description: str) -> str:
    """마크다운 헤딩과 빈 줄을 건너뛴 첫 실제 문장.

    judge 문제의 description은 "## 문제\n정수로 이루어진..." 형태라
    split("\n")[0]이 "## 문제"가 된다.
    """
    for line in description.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return stripped
    return ""


def last_tutor_question(db: DbSession, session_id: str) -> str:
    """튜터가 이 세션에서 **가장 마지막에 던진 질문**을 찾는다. 없으면 빈 문자열.

    학생 답변을 평가하려면 "무엇을 물었는지"가 필요한데, 그 값을 학생
    클라이언트가 보내게 하면 안 된다 -- 질문을 바꿔 보내서 평가를 통과시킬 수
    있다 (본인 학습 기록을 조작하는 것이라 남의 데이터를 보는 문제는 아니지만,
    교육자 화면에 남는 이해도 판단이 거짓이 된다). 그래서 서버가 자기가 남긴
    `AGENT_INTERVENTION` 기록에서 직접 읽는다.

    `activity.question`은 `tutor_agent`의 응답 생성 에이전트가 "이 메시지는
    학생의 답을 기다린다"고 표시할 때만 채워진다
    (`backend_adapter.to_agent_decision`). 그래서 질문이 아닌 개입(단순 힌트)
    뒤에 학생이 말을 걸면 여기서 빈 문자열이 나오고, agent는 그 경우를
    "학생이 먼저 말을 걸었다"로 취급한다.
    """
    for e in reversed(trace_service.all_events(db, session_id)):
        if EventType(e.type) is not EventType.AGENT_INTERVENTION:
            continue
        activity = (e.payload or {}).get("activity")
        if not isinstance(activity, dict):
            continue
        question = activity.get("question")
        if isinstance(question, str) and question.strip():
            return question.strip()
        # 질문 없는 개입을 만나면 더 뒤로 가지 않는다. 그보다 앞선 질문은 이미
        # 다른 개입으로 덮여서, 학생이 지금 답하는 대상이 아니다.
        return ""
    return ""


def build_context(
    db: DbSession,
    session_id: str,
    repo: ProblemRepository,
    *,
    state: ProcessState | None = None,
    now: datetime | None = None,
) -> AgentContext:
    session = store.require_session(db, session_id)
    problem = repo.get(session.problem_id)
    events = trace_service.all_events(db, session_id)
    snapshot = store.latest_snapshot(db, session_id)
    state = state or evaluate(db, session_id, now=now)

    f = state.features
    last = f.last_result

    previous: list[dict] = []
    for e in events:
        etype = EventType(e.type)
        if etype in (EventType.AGENT_TRIGGER, EventType.AGENT_INTERVENTION):
            p = e.payload or {}
            activity = p.get("activity") if isinstance(p.get("activity"), dict) else {}
            previous.append(
                {
                    "seq": e.seq,
                    "type": etype.value,
                    "trigger": p.get("trigger"),
                    "action": p.get("action"),
                    "reason": p.get("reason"),
                    # **학생에게 실제로 한 말**도 같이 넘긴다. reason은 내부 근거
                    # ("학생이 while 조건을 오해하고 있습니다")라서, 이것만 주면
                    # agent가 자기가 무슨 말을 했는지 모른 채 같은 힌트를 다시
                    # 만든다. 실제로 힌트가 반복되는 원인이었다.
                    "message": activity.get("message"),
                }
            )

    return AgentContext(
        session_id=session_id,
        problem={
            "problem_id": problem.problem_id,
            "title": problem.title,
            "concepts": problem.concepts,
            # 첫 줄이 아니라 **첫 의미 있는 줄**을 쓴다. judge 문제의 description은
            # 마크다운이라 첫 줄이 리터럴 "## 문제"다. 그걸 그대로 넣으면
            # 모든 에이전트 프롬프트에 무의미한 문자열이 들어간다.
            "description_summary": _first_prose_line(problem.description),
            "function_name": problem.function_name,
        },
        current_code=snapshot.code if snapshot else "",
        current_code_version=snapshot.version if snapshot else 0,
        judge_result=None
        if last is None
        else {
            "mode": last.mode,
            "status": last.status.value,
            "passed": last.passed,
            "total": last.total,
            # 학생 응답에서는 빼지만 Agent에는 준다 (backend_plan §7.2, feature_plan §3).
            "failed_categories": last.failed_categories,
        },
        recent_trace=recent_trace_labels(events, RECENT_TRACE_LIMIT),
        features=features_to_dict(f),
        process_status=state.status.value,
        trigger=state.trigger.value if state.trigger else None,
        evidence=state.evidence,
        previous_interventions=previous[-5:],
    )
