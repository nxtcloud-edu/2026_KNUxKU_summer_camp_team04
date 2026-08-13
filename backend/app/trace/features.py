"""Process Feature Extractor.

Raw event를 Agent가 이해할 수 있는 feature로 압축한다 (backend_plan §11).

이 모듈에서 가장 중요한 정의상 결정
------------------------------------
**SYNTAX_ERROR / RUNTIME_ERROR / TIME_LIMIT 결과는 0점이 아니라 "관측 없음"이다.**
recent_scores, same_result_count, progress_delta 계산에서 제외한다.

왜 중요한가:
  * syntax error를 0으로 세면 `3/5 -> syntax -> 3/5`가 [3, 0, 3]이 되어
    progress_delta = +3 -> monitor가 PROGRESSING을 선언하고 명백히 막힌 학생을 방치한다.
  * 반대로 `3/5 -> 3/5 -> syntax -> 3/5 -> 3/5`는 동일 결과 streak이 2로 리셋되어
    영원히 REPEATED_FAILURE가 뜨지 않는다.
  * 그리고 backend_plan §22.3의 "syntax error 1회는 Agent를 호출하지 않는다"가
    특례 규칙 없이 **구조적으로** 도출된다.

now는 주입 가능하다. 이 파라미터 하나가 0.2초 테스트 스위트와 flaky 스위트를 가른다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from sqlmodel import Session as DbSession

from app.clock import seconds_between, utcnow
from app.config import DEFAULT_MONITOR_CONFIG, MonitorConfig
from app.enums import ERROR_STATUSES, SCORED_STATUSES, EventType, JudgeStatus, RegionTag
from app.errors import SessionNotFound
from app.models import CodeSnapshot, Event, Session
from app.sessions import store
from app.trace import service as trace_service


@dataclass(frozen=True)
class ResultObservation:
    seq: int
    at: datetime
    mode: str
    status: JudgeStatus
    passed: int
    total: int
    # 이 결과가 채점한 코드의 버전. 스냅샷과 결과의 **순서 비교는 전부 이걸로 한다.**
    # created_at 비교는 안 된다: server_timestamp는 microsecond를 자르므로
    # 빠르게 이어지는 편집/실행이 전부 같은 초에 몰리고, 그러면 "직전 결과 이후의 편집"이
    # 그 이전 편집까지 쓸어담아 large_change_detected가 거짓 양성을 낸다.
    # version은 seq와 마찬가지로 서버가 원자적으로 할당하는 단조 카운터라 안전하다.
    code_version: int = 0
    failed_categories: list[str] = field(default_factory=list)

    @property
    def signature(self) -> tuple[str, int, int]:
        """same_result_count가 비교하는 키.

        passed만 비교하면 틀린다: run 모드는 public만 채점하고(func_sum_list는 total=1)
        submit은 public+hidden을 채점한다(total=4). `1/1 -> 1/4 -> 1/1`인 학생은
        passed가 세 번 1이지만 같은 결과를 반복한 게 아니다 -- 가운데 관측은 새 정보다.
        total을 넣으면 특례 없이 두 모드가 분리되고, status를 넣으면
        미래의 ACCEPTED 5/5와 WRONG_ANSWER 5/5가 충돌할 일이 없다.

        failed_categories는 일부러 뺐다: 오늘의 Pyodide judge가 이걸 안정적으로
        생산하지 못하는데, 동일성을 요구하면 streak이 조용히 탐지 불가능해진다.
        """
        return (self.status.value, self.passed, self.total)


@dataclass(frozen=True)
class ProcessFeatures:
    elapsed_seconds: int = 0
    run_count: int = 0
    submit_count: int = 0
    attempt_count: int = 0
    recent_scores: list[int] = field(default_factory=list)
    same_result_count: int = 0
    progress_delta: int = 0
    improved_recently: bool = False
    seconds_without_progress: int = 0
    same_region_edit_count: int = 0
    repeated_edit_region: str | None = None
    edits_since_progress: int = 0
    edits_in_result_streak: int = 0
    undo_count: int = 0
    hint_count: int = 0
    large_change_detected: bool = False
    recent_error_types: list[str] = field(default_factory=list)
    consecutive_error_count: int = 0
    snapshot_count: int = 0
    last_result: ResultObservation | None = None
    # monitor가 쓰는 보조 상태 (feature라기보단 문맥)
    last_progress_at: datetime | None = None
    last_hint_seq: int | None = None
    last_trigger_seq: int | None = None
    last_trigger_at: datetime | None = None


def _to_observation(e: Event) -> ResultObservation | None:
    p = e.payload or {}
    try:
        status = JudgeStatus(p["status"])
    except (KeyError, ValueError):
        return None
    return ResultObservation(
        seq=e.seq,
        at=e.server_timestamp,
        mode=str(p.get("mode", "run")),
        status=status,
        passed=int(p.get("passed", 0)),
        total=int(p.get("total", 0)),
        code_version=e.code_version or 0,
        failed_categories=list(p.get("failed_categories") or []),
    )


def _progress_version(
    scored: list[ResultObservation],
    activity_success_at: datetime | None,
    last_progress_at: datetime | None,
) -> int:
    """진전 anchor에 해당하는 code_version.

    편집 창을 자르는 기준이다. anchor가 ACTIVITY_RESPONSE(코드 버전이 없다)라면
    그 시점까지의 최신 결과 버전을 쓴다.
    """
    best = -1
    version = 1
    for r in scored:
        if r.passed > best:
            best = r.passed
            version = r.code_version
    if (
        activity_success_at is not None
        and last_progress_at is not None
        and activity_success_at == last_progress_at
        and scored
    ):
        version = scored[-1].code_version
    return version


def _trailing_run(items: list, key) -> int:  # type: ignore[no-untyped-def]
    """말단 연속 동일 구간의 길이."""
    if not items:
        return 0
    last = key(items[-1])
    n = 0
    for item in reversed(items):
        if key(item) != last:
            break
        n += 1
    return n


def extract_features(
    db: DbSession,
    session_id: str,
    *,
    now: datetime | None = None,
    cfg: MonitorConfig | None = None,
    session: Session | None = None,
    events: list[Event] | None = None,
    snapshots: list[CodeSnapshot] | None = None,
) -> ProcessFeatures:
    """세션의 Process Feature를 계산한다.

    전체 스캔이다 (세션당 O(10^2) 행). 증분 캐시를 넣지 않는다 --
    캐시 무효화 버그가 계산 비용보다 훨씬 비싸다.
    """
    cfg = cfg or DEFAULT_MONITOR_CONFIG
    now = now or utcnow()

    if session is None:
        session = store.get_session(db, session_id)
        if session is None:
            raise SessionNotFound(session_id)
    if events is None:
        events = trace_service.all_events(db, session_id)
    if snapshots is None:
        snapshots = store.all_snapshots(db, session_id)

    results: list[ResultObservation] = []
    undo_count = 0
    hint_count = 0
    last_hint_seq: int | None = None
    last_trigger_seq: int | None = None
    last_trigger_at: datetime | None = None
    activity_success_at: datetime | None = None

    for e in events:
        etype = EventType(e.type)
        if etype is EventType.TEST_RESULT:
            obs = _to_observation(e)
            if obs is not None:
                results.append(obs)
        elif etype is EventType.UNDO:
            undo_count += 1
        elif etype is EventType.HINT_REQUEST:
            hint_count += 1
            last_hint_seq = e.seq
        elif etype is EventType.AGENT_TRIGGER:
            last_trigger_seq = e.seq
            last_trigger_at = e.server_timestamp
        elif etype is EventType.ACTIVITY_RESPONSE:
            if (e.payload or {}).get("result") == "CORRECT":
                activity_success_at = e.server_timestamp

    scored = [r for r in results if r.status in SCORED_STATUSES]
    errored = [r for r in results if r.status in ERROR_STATUSES]

    run_count = sum(1 for r in results if r.mode == "run")
    submit_count = sum(1 for r in results if r.mode == "submit")
    attempt_count = run_count + submit_count

    recent_scores = [r.passed for r in scored[-cfg.recent_score_window :]]
    same_result_count = _trailing_run(scored, lambda r: r.signature)
    progress_delta = scored[-1].passed - scored[-2].passed if len(scored) >= 2 else 0

    window = scored[-3:]
    improved_recently = any(
        window[i + 1].passed > window[i].passed for i in range(len(window) - 1)
    )

    # ---- 진전 anchor -----------------------------------------------------
    # "아무 증가"가 아니라 "개인 최고 기록 갱신"이다.
    # 4/5 -> 3/5 -> 4/5에서 두 번째 4/5는 회복이지 진전이 아니므로
    # 90초 시계는 첫 4/5부터 계속 흘러야 한다.
    last_progress_at: datetime | None = None
    best = -1
    for r in scored:
        if r.passed > best:
            best = r.passed
            last_progress_at = r.at
    if activity_success_at is not None and (
        last_progress_at is None or activity_success_at > last_progress_at
    ):
        last_progress_at = activity_success_at

    progress_anchor = last_progress_at or session.started_at
    # 시계는 항상 서버다. client_timestamp는 왜곡되고 위조 가능하다.
    seconds_without_progress = seconds_between(progress_anchor, now)

    # ---- 편집 feature ----------------------------------------------------
    # 아래의 모든 "X 이후의 편집" 창은 created_at이 아니라 **code_version**으로 자른다.
    # server_timestamp는 microsecond를 자르므로 빠르게 이어지는 편집/실행이 같은 초에
    # 몰리고, 그러면 창이 의도보다 넓어져 거짓 양성이 난다 (ResultObservation 주석 참조).
    #
    # version==1은 제외한다: 문제 템플릿이지 학생의 편집이 아니고,
    # old_code=None이라 change_ratio가 1.0으로 나온다.
    edits = [s for s in snapshots if s.version > 1]

    progress_version = _progress_version(scored, activity_success_at, last_progress_at)
    edits_since_progress = [s for s in edits if s.version > progress_version]

    tagged = [
        s for s in edits_since_progress if s.primary_region != RegionTag.OTHER.value
    ]
    same_region_edit_count = _trailing_run(tagged, lambda s: s.primary_region)
    repeated_edit_region = (
        tagged[-1].primary_region if tagged and same_region_edit_count >= 1 else None
    )

    # 동일 결과 streak이 시작된 시점 이후의 편집 수. monitor R5b가 읽는다.
    # "학생이 아무것도 안 고치고 Run만 3번" 케이스를 잡기 위한 것이므로 창이
    # progress anchor가 아니라 **streak의 첫 결과**여야 한다:
    # 편집 -> 3/5 -> 3/5 -> 3/5 인 학생은 편집이 streak 이전이라 0이어야 맞다.
    streak_start_version = (
        scored[-same_result_count].code_version
        if same_result_count >= 1
        else progress_version
    )
    edits_in_result_streak = sum(1 for s in edits if s.version > streak_start_version)

    # ---- 대규모 변화 -----------------------------------------------------
    # 창은 "세션 시작 이후"가 아니라 "직전 결과 이후"다.
    # 의미: *현재 결과를 만든 변경*이 대규모 재작성이었는가?
    # 그게 정확히 agent_plan §14 시나리오 C(큰 재작성 -> 즉시 5/5 -> VERIFY)다.
    # "세션 시작 이후" 창이면 한 번 크게 붙여넣은 세션이 영원히 플래그된다.
    prev_boundary_version = scored[-2].code_version if len(scored) >= 2 else 1
    large_change_detected = any(
        s.change_ratio >= cfg.large_change_ratio
        and s.change_size >= cfg.large_change_min_lines
        and s.seconds_since_parent <= cfg.large_change_window_seconds
        and s.version > prev_boundary_version
        for s in edits
    )

    return ProcessFeatures(
        elapsed_seconds=seconds_between(session.started_at, now),
        run_count=run_count,
        submit_count=submit_count,
        attempt_count=attempt_count,
        recent_scores=recent_scores,
        same_result_count=same_result_count,
        progress_delta=progress_delta,
        improved_recently=improved_recently,
        seconds_without_progress=seconds_without_progress,
        same_region_edit_count=same_region_edit_count,
        repeated_edit_region=repeated_edit_region,
        edits_since_progress=len(edits_since_progress),
        edits_in_result_streak=edits_in_result_streak,
        undo_count=undo_count,
        hint_count=hint_count,
        large_change_detected=large_change_detected,
        recent_error_types=[r.status.value for r in errored[-5:]],
        # 필터링 안 한 전체 리스트 기준: 에러 사이에 정상 결과가 끼면 연속이 끊긴다.
        consecutive_error_count=_trailing_run(
            results, lambda r: r.status in ERROR_STATUSES
        )
        if results and results[-1].status in ERROR_STATUSES
        else 0,
        snapshot_count=len(snapshots),
        last_result=results[-1] if results else None,
        last_progress_at=last_progress_at,
        last_hint_seq=last_hint_seq,
        last_trigger_seq=last_trigger_seq,
        last_trigger_at=last_trigger_at,
    )
