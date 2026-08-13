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
            previous.append(
                {
                    "seq": e.seq,
                    "type": etype.value,
                    "trigger": p.get("trigger"),
                    "action": p.get("action"),
                    "reason": p.get("reason"),
                }
            )

    return AgentContext(
        session_id=session_id,
        problem={
            "problem_id": problem.problem_id,
            "title": problem.title,
            "concepts": problem.concepts,
            "description_summary": problem.description.split("\n")[0],
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
