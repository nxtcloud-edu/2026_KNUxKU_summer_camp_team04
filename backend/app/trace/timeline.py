"""Coding Timeline (feature_plan §22).

**항상 seq 오름차순.** 절대 timestamp 정렬이 아니다 -- 배치 이벤트는
server_timestamp가 동일하고(microsecond 절삭) 클라이언트 시계는 무의미하다.

collapse=true(기본)는 연속 EDIT을 하나로 합친다. debounce가 두 Run 사이에
스냅샷을 ~10개 만드는데 feature_plan §22의 목업은 EDIT 하나를 보여준다.
합치지 않으면 데모 타임라인을 읽을 수가 없다.
collapse=false는 Process Replay(§23)용 전체 충실도.
"""
from __future__ import annotations

from typing import Any

from app.clock import seconds_between, utcnow
from app.enums import EventType, JudgeStatus, SessionStatus
from app.models import Event, Session
from app.trace.diff import region_label
from app.trace.schemas import TimelineEntry, TimelineResponse, TimelineSummary

_KIND: dict[EventType, str] = {
    EventType.SESSION_START: "START",
    EventType.CODE_SNAPSHOT: "EDIT",
    EventType.RUN: "RUN",
    EventType.SUBMIT: "SUBMIT",
    EventType.UNDO: "UNDO",
    EventType.RESET: "RESET",
    EventType.HINT_REQUEST: "HINT",
    EventType.ACTIVITY_OPENED: "ACTIVITY",
    EventType.ACTIVITY_RESPONSE: "ACTIVITY",
    EventType.SESSION_END: "END",
    EventType.AGENT_TRIGGER: "AGENT",
    EventType.AGENT_INTERVENTION: "AGENT",
    EventType.SYNTAX_ERROR: "ERROR",
    EventType.RUNTIME_ERROR: "ERROR",
}

_ERROR_LABEL = {
    JudgeStatus.SYNTAX_ERROR: "SYNTAX ERROR",
    JudgeStatus.RUNTIME_ERROR: "RUNTIME ERROR",
    JudgeStatus.TIME_LIMIT: "TIME LIMIT",
    JudgeStatus.INTERNAL_ERROR: "INTERNAL ERROR",
}


def classify(e: Event) -> tuple[str, str]:
    """이벤트 하나를 (kind, label)로. TEST_RESULT만 payload에 따라 갈린다."""
    etype = EventType(e.type)
    p = e.payload or {}

    if etype is EventType.TEST_RESULT:
        try:
            status = JudgeStatus(p.get("status", ""))
        except ValueError:
            status = JudgeStatus.INTERNAL_ERROR
        # SYNTAX_ERROR/RUNTIME_ERROR를 별도 이벤트로 만들지 않는 대신
        # 여기서 kind="ERROR"로 렌더한다 -- 화면은 같고 데이터의 진실은 하나다.
        if status in _ERROR_LABEL:
            return "ERROR", _ERROR_LABEL[status]
        kind = "SUBMIT" if p.get("mode") == "submit" else "RUN"
        return kind, f"{kind} {p.get('passed', 0)}/{p.get('total', 0)}"

    if etype is EventType.CODE_SNAPSHOT:
        region = p.get("primary_region", "other")
        lines = len(p.get("changed_lines") or [])
        if p.get("deduplicated"):
            return "EDIT", "변경 없음"
        return "EDIT", f"{region_label(region)} 영역 수정 ({lines}줄)"

    if etype is EventType.AGENT_TRIGGER:
        return "AGENT", f"AGENT TRIGGER: {p.get('trigger', '')}"

    if etype is EventType.AGENT_INTERVENTION:
        return "AGENT", f"AGENT: {p.get('action', '')}"

    if etype is EventType.SESSION_START:
        return "START", "START"

    if etype is EventType.SESSION_END:
        return "END", "END"

    if etype is EventType.ACTIVITY_OPENED:
        return "ACTIVITY", f"ACTIVITY 시작: {p.get('type', '')}"

    if etype is EventType.ACTIVITY_RESPONSE:
        return "ACTIVITY", f"ACTIVITY 응답: {p.get('result', '')}"

    return _KIND.get(etype, "EDIT"), etype.value


def _entry(e: Event) -> TimelineEntry:
    kind, label = classify(e)
    p = e.payload or {}
    detail: dict[str, Any] = {}
    if kind in ("RUN", "SUBMIT"):
        detail = {
            "passed": p.get("passed"),
            "total": p.get("total"),
            "status": p.get("status"),
            "runtime_ms": p.get("runtime_ms"),
        }
    elif kind == "ERROR":
        detail = {"status": p.get("status"), "message": p.get("message")}
    elif kind == "EDIT":
        detail = {
            "primary_region": p.get("primary_region"),
            "changed_lines": p.get("changed_lines"),
            "change_ratio": p.get("change_ratio"),
            "snapshot_count": 1,
        }
    elif kind == "AGENT":
        detail = {"trigger": p.get("trigger"), "evidence": p.get("evidence")}
    return TimelineEntry(
        seq=e.seq,
        at=e.server_timestamp,
        kind=kind,  # type: ignore[arg-type]
        label=label,
        event_type=EventType(e.type),
        code_version=e.code_version,
        detail=detail,
    )


def _collapse(entries: list[TimelineEntry]) -> list[TimelineEntry]:
    out: list[TimelineEntry] = []
    for entry in entries:
        if entry.kind == "EDIT" and out and out[-1].kind == "EDIT":
            prev = out[-1]
            count = prev.detail.get("snapshot_count", 1) + 1
            regions = set(prev.detail.get("regions") or [prev.detail.get("primary_region")])
            regions.add(entry.detail.get("primary_region"))
            regions.discard(None)
            merged_detail = {
                **prev.detail,
                "snapshot_count": count,
                "from_version": prev.detail.get("from_version", prev.code_version),
                "to_version": entry.code_version,
                "regions": sorted(regions),
            }
            primary = entry.detail.get("primary_region") or "other"
            out[-1] = TimelineEntry(
                seq=prev.seq,
                at=prev.at,
                kind="EDIT",
                label=f"{region_label(primary)} 영역 수정 ×{count}",
                event_type=prev.event_type,
                code_version=entry.code_version,
                detail=merged_detail,
            )
        else:
            out.append(entry)
    return out


def build_timeline(
    session: Session, events: list[Event], *, collapse: bool = True
) -> TimelineResponse:
    ordered = sorted(events, key=lambda e: e.seq)
    entries = [_entry(e) for e in ordered]
    if collapse:
        entries = _collapse(entries)

    edit_count = sum(
        1 for e in ordered if EventType(e.type) is EventType.CODE_SNAPSHOT
    )
    run_count = 0
    submit_count = 0
    best_passed: int | None = None
    for e in ordered:
        if EventType(e.type) is not EventType.TEST_RESULT:
            continue
        p = e.payload or {}
        if p.get("mode") == "submit":
            submit_count += 1
        else:
            run_count += 1
        if p.get("status") in (JudgeStatus.ACCEPTED.value, JudgeStatus.WRONG_ANSWER.value):
            passed = int(p.get("passed", 0))
            best_passed = passed if best_passed is None else max(best_passed, passed)

    end = session.finished_at or (ordered[-1].server_timestamp if ordered else utcnow())

    return TimelineResponse(
        session_id=session.id,
        problem_id=session.problem_id,
        status=SessionStatus(session.status),
        entries=entries,
        summary=TimelineSummary(
            edit_count=edit_count,
            run_count=run_count,
            submit_count=submit_count,
            trigger_count=sum(
                1 for e in ordered if EventType(e.type) is EventType.AGENT_TRIGGER
            ),
            best_passed=best_passed,
            total_seconds=seconds_between(session.started_at, end),
        ),
    )


def recent_trace_labels(events: list[Event], limit: int = 10) -> list[str]:
    """agent context builder용. 최근 의미 있는 이벤트의 라벨만.

    타임라인 라벨러를 재사용한다 -- 데모 화면과 agent가 같은 문자열을 본다.
    """
    meaningful = [
        e
        for e in sorted(events, key=lambda e: e.seq)
        if EventType(e.type)
        in {
            EventType.TEST_RESULT,
            EventType.CODE_SNAPSHOT,
            EventType.HINT_REQUEST,
            EventType.AGENT_TRIGGER,
            EventType.AGENT_INTERVENTION,
            EventType.ACTIVITY_RESPONSE,
        }
    ]
    return [classify(e)[1] for e in meaningful[-limit:]]
