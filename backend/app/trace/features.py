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
from app.enums import (
    ERROR_STATUSES,
    SCORED_STATUSES,
    SYSTEM_STATUSES,
    EventType,
    JudgeStatus,
    RegionTag,
)
from app.errors import SessionNotFound
from app.models import CodeSnapshot, Event, Session
from app.sessions import store
from app.trace import service as trace_service


#: "학생이 무언가 했다"로 보는 이벤트. R7d(완전 무활동)의 시계를 리셋한다.
#:
#: TEST_RESULT를 포함하는 이유: RUN/SUBMIT 클라이언트 이벤트 없이 채점 결과만
#: 기록되는 경로(judge/router.py)가 있어서, 결과를 빼면 "방금 실행하고 결과를
#: 읽는 중"인 학생이 무활동으로 잡힌다.
#: AGENT_TRIGGER / AGENT_INTERVENTION / SESSION_START는 **서버가** 쓴 행이므로 제외한다
#: -- 개입 그 자체가 시계를 리셋하면 유휴 학생이 영원히 유휴로 안 잡힌다.
ACTIVITY_EVENT_TYPES: frozenset[EventType] = frozenset(
    {
        EventType.CODE_SNAPSHOT,
        EventType.RUN,
        EventType.SUBMIT,
        EventType.UNDO,
        EventType.RESET,
        EventType.HINT_REQUEST,
        EventType.ACTIVITY_OPENED,
        EventType.ACTIVITY_RESPONSE,
        EventType.TEST_RESULT,
    }
)


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
    # 마지막 **편집** 이후 흐른 시간. seconds_without_progress와 다르다:
    # 그건 "마지막 채점 개선 이후"라 학생이 활발히 타이핑하는 중에도 계속
    # 증가하므로 "지금 손을 놓고 있는가"를 판정할 수 없다. 편집이 하나도 없으면
    # 세션 시작을 기준으로 잰다.
    seconds_since_last_edit: int = 0
    # 마지막 **활동** 이후 흐른 시간. seconds_since_last_edit보다 넓다:
    # 편집뿐 아니라 실행/제출/힌트요청/undo/reset/활동응답까지 전부 활동으로 센다.
    # R7d(완전 무활동)가 읽는다 -- "편집은 멈췄지만 방금 실행해서 결과를 보고 있는"
    # 학생을 유휴로 오판하지 않기 위해 편집 시계와 분리한다.
    seconds_since_last_activity: int = 0
    # 마지막 AGENT_TRIGGER 이후의 편집 수. 편집만으로 발화하는 규칙(R7b/R7c)이
    # "지난번에 찔렀는데 학생이 아무것도 안 했으면 또 찌르지 않는다"를 지키는 데 쓴다.
    # 트리거 이력이 없으면 전체 편집 수와 같다.
    edits_since_last_trigger: int = 0
    # 마지막 AGENT_TRIGGER 이후의 **모든** 활동 수. R7d의 anti-spam 가드다.
    # edits_since_last_trigger로는 부족하다: 무활동 규칙은 정의상 편집이 없는
    # 구간에서 발화하므로, 편집 수로 막으면 첫 발화 자체가 불가능해진다.
    # 트리거 이력이 없으면 세션 전체의 활동 수와 같다(활동이 0이면 발화하지 않는다
    # -- 문제를 열어놓고 아직 아무것도 시작하지 않은 학생은 유휴가 아니라 독해 중이다).
    activity_since_last_trigger: int = 0
    # 마지막 채점 결과 이후의 편집 수 = "고쳐놓고 아직 안 돌려본 것"이 있는가.
    edits_since_last_result: int = 0
    # 그 미검증 편집 중에 대규모 변경(붙여넣기 의심)이 있는가.
    # large_change_detected와 창이 다르다 -- 계산부 주석 참고.
    large_change_unverified: bool = False
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
    # 채점기 고장(INTERNAL_ERROR)은 학생에 대한 관측이 **아니다.** 연속 에러
    # streak 계산에서 통째로 빼서 세지도 않고 끊지도 않는다.
    #
    # 세면: 도커가 죽어 있을 때 Run 세 번으로 REPEATED_FAILURE가 발화한다.
    # 끊으면: 학생의 진짜 3연속 런타임 에러 중간에 채점기가 한 번 딸꾹질하면
    #         streak이 리셋되어 정작 필요한 개입을 놓친다.
    # 둘 다 틀렸으므로 투명하게 만든다.
    observed = [r for r in results if r.status not in SYSTEM_STATUSES]

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

    # ---- 편집 시계 -------------------------------------------------------
    # "마지막 편집 이후"를 잰다. 편집이 없으면 세션 시작 기준 -- 문제를 열어놓고
    # 아무것도 안 친 학생도 유휴로 잡히게 하려는 것이다.
    # 여기서도 시계는 서버다(server_timestamp가 아니라 스냅샷의 created_at을 쓰는
    # 이유: 스냅샷은 편집 그 자체이고, 이벤트 seq는 배치 전송 타이밍에 흔들린다).
    last_edit_at = snapshots[-1].created_at if snapshots else session.started_at
    seconds_since_last_edit = seconds_between(last_edit_at, now)

    # 마지막 트리거 이후의 편집 수. 스냅샷에는 seq가 없으므로 CODE_SNAPSHOT
    # **이벤트**의 seq로 센다.
    edits_since_last_trigger = sum(
        1
        for e in events
        if EventType(e.type) is EventType.CODE_SNAPSHOT
        and (last_trigger_seq is None or e.seq > last_trigger_seq)
    )

    # ---- 완전 무활동 시계 (R7d) -------------------------------------------
    # 편집 시계와 분리한다. 편집만 보면 "방금 Run을 눌러 결과를 읽는 중"인 학생이
    # 유휴로 잡히고, 반대로 활동 전체를 보면 churn 판정(R7c)이 실행 때문에 리셋된다.
    # 두 시계는 서로 다른 질문에 답하므로 둘 다 필요하다.
    activity_times = [
        e.server_timestamp for e in events if EventType(e.type) in ACTIVITY_EVENT_TYPES
    ]
    # 스냅샷의 created_at도 후보에 넣는다: 편집은 배치로 전송되므로 이벤트 seq/시각이
    # 흔들리지만 스냅샷은 편집 그 자체다 (seconds_since_last_edit과 같은 이유).
    if snapshots:
        activity_times.append(snapshots[-1].created_at)
    last_activity_at = max(activity_times) if activity_times else session.started_at
    seconds_since_last_activity = seconds_between(last_activity_at, now)

    activity_since_last_trigger = sum(
        1
        for e in events
        if EventType(e.type) in ACTIVITY_EVENT_TYPES
        and (last_trigger_seq is None or e.seq > last_trigger_seq)
    )

    # ---- 아직 실행해보지 않은 편집 ----------------------------------------
    # large_change_detected와 창이 다르다. 그건 "**현재 결과를 만든** 변경이
    # 대규모였는가"(R2: 붙여넣고 통과했다)라서 결과 이전의 편집을 포함한다.
    # 이쪽은 "결과 **이후에** 고쳐놓고 아직 안 돌려봤는가"다 -- R7b가 잡으려는
    # '붙여넣고 실행조차 안 함'이 정확히 이것이고, 창을 구분하지 않으면
    # 큰 편집 -> 실행(문법 오류) 한 번에도 R7b가 발화한다(실제로 겪었다).
    last_result_version = results[-1].code_version if results else 0
    unverified_edits = [s for s in edits if s.version > last_result_version]
    # **학생의 첫 편집은 제외한다.** 템플릿(3줄 `pass`)에서 첫 초안으로 가는 변경은
    # change_ratio/change_size 기준을 거의 항상 넘긴다 -- 붙여넣기가 아니라 정상적인
    # 작성인데도 매번 붙잡히면 개입이 소음이 된다.
    #
    # 이걸 빼면 "첫 행동이 붙여넣기"인 학생을 R7b가 놓치지만, 그 학생은 붙여넣은
    # 코드를 실행해서 통과하는 순간 R2(대규모 변경 직후 통과)가 잡는다. 정작
    # R7b만 잡을 수 있는 건 "이미 쓰던 코드를 통째로 갈아치우고 실행조차 안 한"
    # 경우이고, 거기엔 반드시 앞선 편집이 존재한다.
    first_edit_version = edits[0].version if edits else 0
    replaceable = [s for s in unverified_edits if s.version > first_edit_version]
    large_change_unverified = any(
        s.change_ratio >= cfg.large_change_ratio
        and s.change_size >= cfg.large_change_min_lines
        and s.seconds_since_parent <= cfg.large_change_window_seconds
        for s in replaceable
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
        # 정상 결과(ACCEPTED/WRONG_ANSWER)가 끼면 연속이 끊긴다. 그래서 errored가
        # 아니라 observed(= 시스템 오류만 제외한 전체) 기준으로 센다.
        consecutive_error_count=_trailing_run(
            observed, lambda r: r.status in ERROR_STATUSES
        )
        if observed and observed[-1].status in ERROR_STATUSES
        else 0,
        snapshot_count=len(snapshots),
        seconds_since_last_edit=seconds_since_last_edit,
        seconds_since_last_activity=seconds_since_last_activity,
        edits_since_last_trigger=edits_since_last_trigger,
        activity_since_last_trigger=activity_since_last_trigger,
        edits_since_last_result=len(unverified_edits),
        large_change_unverified=large_change_unverified,
        last_result=results[-1] if results else None,
        last_progress_at=last_progress_at,
        last_hint_seq=last_hint_seq,
        last_trigger_seq=last_trigger_seq,
        last_trigger_at=last_trigger_at,
    )
