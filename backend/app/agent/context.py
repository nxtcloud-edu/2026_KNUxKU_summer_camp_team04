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
from app.config import get_settings
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
    # cfg를 반드시 넘긴다. 생략하면 monitor가 DEFAULT_MONITOR_CONFIG(코드에 박힌
    # 기본값)로 떨어져서 MONITOR_* 환경변수가 통째로 무시된다 (judge/router.py,
    # trace/router.py의 같은 호출들과 동일한 이유 — CLAUDE.md "설정" 절 참고).
    # `/agent/decide`(SOS 경로)가 이 함수를 state 없이 부르므로, 여기서 빠뜨리면
    # SOS로 보는 evidence/status가 하트비트·submit 경로와 다른 임계값으로 계산된다.
    state = state or evaluate(db, session_id, now=now, cfg=get_settings().monitor)

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
