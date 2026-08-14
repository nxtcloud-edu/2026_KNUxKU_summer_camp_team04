"""Lightweight Process Monitor (backend_plan §12).

Monitor는 Agent가 아니다. LLM을 부르지 않고 결정론적 규칙만으로
"지금 Agent를 불러야 하는가"를 판정한다.

pure/recording 분리 -- 이 모듈의 가장 중요한 구조적 결정
--------------------------------------------------------
evaluate()는 아무것도 쓰지 않는다. evaluate_and_record()만 AGENT_TRIGGER를 쓴다.

  GET  /sessions/{id}/process-state  -> evaluate()
  POST /sessions/{id}/results        -> evaluate_and_record()

cooldown 상태가 AGENT_TRIGGER 이벤트에 살기 때문이다. 데모의 Process State 패널은
/process-state를 몇 초마다 폴링한다. GET이 cooldown을 소진해버리면 trigger 직후
첫 폴링이 그걸 먹고, 정작 agent를 호출해야 할 실제 Run이 cooldown에 걸린다.
(GET이 상태를 바꾸는 건 그 자체로도 틀렸다.)

규칙 체인 (first match wins)
---------------------------
  R0  HELP_REQUESTED   [cooldown 무시] 새 HINT_REQUEST
  --- 이하 cooldown 적용 ---
  R1  COOLDOWN GATE    status는 분류하되 trigger만 죽인다
  R1s SYSTEM ERROR     마지막 결과가 채점기 고장 -> 판단 보류, trigger 없음
  R2  UNDERSTANDING_UNCERTAIN  ACCEPTED + large_change    ★시나리오 C
  R3  PROGRESS GUARD   progress_delta > 0 or improved     ★시나리오 1
  R4  SOLVED           ACCEPTED
  R5  REPEATED_FAILURE same_result>=3 and same_region>=2  ★시나리오 2
  R5b REPEATED_FAILURE same_result>=3 and streak 내 편집 0
  R6  REPEATED_ERROR   consecutive_error>=3
  R7  NO_PROGRESS      90초 무진전 and attempt>=2
  --- 이하 채점 결과 없이 편집만으로 발화한다 ---
  R7b UNDERSTANDING_UNCERTAIN  대규모 변경 and 그 후 멈춤
  R7c NO_PROGRESS      같은 영역 churn and 편집 멈춤
  R7d NO_PROGRESS      아무 활동도 없이 10초 경과 (활동 1건 이상 있었던 세션)
  R8  PRODUCTIVE_STRUGGLE  attempt>=2
  R9  기본             PROGRESSING

R7까지는 전부 TEST_RESULT를 요구한다는 점이 중요하다 -- attempt_count조차
클라이언트의 RUN/SUBMIT 이벤트가 아니라 **서버가 채점하며 쓴 결과**만 센다.
그래서 R7b/R7c가 없으면 "실행을 한 번도 안 누른 학생"에게는 R0(도움 요청)
말고 어떤 규칙도 발화할 수 없다.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlmodel import Session as DbSession

from app.clock import seconds_between, utcnow
from app.config import DEFAULT_MONITOR_CONFIG, MonitorConfig
from app.enums import (
    SYSTEM_STATUSES,
    EventSource,
    EventType,
    JudgeStatus,
    ProcessStatus,
    TriggerType,
)
from app.models import Session
from app.sessions import store
from app.trace import service as trace_service
from app.trace.diff import region_label
from app.trace.features import ProcessFeatures, extract_features


@dataclass(frozen=True)
class ProcessState:
    status: ProcessStatus
    trigger: TriggerType | None
    reason: str
    evidence: list[str]
    cooldown_active: bool
    cooldown_remaining_seconds: int
    features: ProcessFeatures
    evaluated_at: datetime

    @property
    def triggered(self) -> bool:
        return self.trigger is not None


# --------------------------------------------------------------------- cooldown


def _cooldown(
    f: ProcessFeatures, events_after_trigger_has_result: bool, now: datetime, cfg: MonitorConfig
) -> tuple[bool, int]:
    """backend_plan §12의 "개입 후 최소 30초 **또는** 다음 Run까지"를 문자 그대로 읽는다.

    둘 중 먼저 오는 쪽이 cooldown을 푼다 -> 두 조건이 **모두** 살아 있을 때만 유지된다.

    상태를 sessions 컬럼이 아니라 events에 두는 이유:
      1. trigger는 원래 이벤트다 (계획서가 이미 AGENT_TRIGGER를 이벤트 타입으로 명시).
         컬럼으로 복제하면 동기화 의무가 생긴다.
      2. GET /timeline에 그대로 보인다 -- 데모가 어차피 필요로 하는 "AGENT: TRACE" 마커.
      3. 세션 상태를 조작하는 대신 행 하나를 넣어 cooldown을 테스트할 수 있다.
      4. agent 모듈의 previous_interventions(backend_plan §13)가 공짜로 나온다.
    """
    if f.last_trigger_at is None:
        return False, 0
    elapsed = seconds_between(f.last_trigger_at, now)
    if elapsed >= cfg.cooldown_seconds:
        return False, 0
    if events_after_trigger_has_result:
        return False, 0
    return True, cfg.cooldown_seconds - elapsed


# --------------------------------------------------------------------- evidence


def _evidence(f: ProcessFeatures, cfg: MonitorConfig) -> list[str]:
    """사람이 읽는 근거 문자열.

    서버에서 만드는 이유: feature_plan §21과 frontend_plan §12가 정확히 이 리스트를
    렌더한다. 여기서 만들면 프론트는 멍청한 <ul>이 되고, 문자열이 백엔드 테스트로
    커버되고, agent context builder가 같은 함수를 재사용한다.
    """
    out: list[str] = []
    if f.same_result_count >= 2 and f.last_result is not None:
        r = f.last_result
        out.append(f"동일 결과 {r.passed}/{r.total} ×{f.same_result_count}")
    if f.same_region_edit_count >= 2 and f.repeated_edit_region:
        out.append(
            f"{region_label(f.repeated_edit_region)} 영역 ×{f.same_region_edit_count} 반복 수정"
        )
    if f.attempt_count >= 1 and f.seconds_without_progress >= cfg.no_progress_seconds:
        out.append(f"{f.seconds_without_progress}초 동안 진전 없음")
    if f.consecutive_error_count >= 2 and f.recent_error_types:
        out.append(f"{f.recent_error_types[-1]} ×{f.consecutive_error_count} 연속")
    if f.large_change_detected:
        # 실행이 한 번도 없었으면 "직전 실행 전"이라는 말이 거짓이 된다
        # (R7b는 실행 없이 붙여넣기만 한 세션에서 발화한다).
        out.append(
            "직전 실행 전 대규모 코드 변경"
            if f.attempt_count >= 1
            else "실행 없이 대규모 코드 변경"
        )
    # 편집 시계는 "손을 놓았을 때"만 근거로 의미가 있다. 타이핑 중에는 노이즈다.
    if f.snapshot_count >= 1 and f.seconds_since_last_edit >= cfg.paste_settle_seconds:
        out.append(f"{f.seconds_since_last_edit}초째 편집 없음")
    # 무활동은 편집 없음과 별개로 적는다 -- 실행만 반복하다 멈춘 학생은 위 문장이
    # 오래 전 편집 시각을 가리켜 오해를 만든다.
    if f.seconds_since_last_activity >= cfg.idle_no_activity_seconds:
        out.append(f"{f.seconds_since_last_activity}초째 아무 활동 없음")
    if f.progress_delta > 0:
        out.append(f"직전 실행 대비 +{f.progress_delta} 테스트 통과")
    if f.recent_scores:
        out.append("최근 점수 " + " → ".join(str(s) for s in f.recent_scores))
    if f.hint_count:
        out.append(f"힌트 요청 ×{f.hint_count}")
    return out


# --------------------------------------------------------------------- 규칙 체인


def _classify(
    f: ProcessFeatures, cfg: MonitorConfig
) -> tuple[ProcessStatus, TriggerType | None, str]:
    """R2~R9. first match wins. **순서가 설계다.**

    새 규칙을 추가할 일이 있으면 반드시 R3(진전 가드) **아래**에 넣는다.
    R3가 위에 있다는 사실 자체가, 눈에 띄게 개선 중인 학생을 미래의 공격적인 규칙으로부터
    보호하는 보장이다. R2가 유일한 예외이고, 그 이유는 아래에 적어뒀다.
    """
    last = f.last_result

    # R1s 채점기 고장 게이트.
    #
    # 마지막 결과가 INTERNAL_ERROR면 우리는 학생 코드에 대해 **아무것도 관측하지
    # 못했다.** 여기서 개입하면 원인이 채점 서버인데 "반복문을 살펴보세요" 같은
    # 엉뚱한 힌트가 나간다. 학생에게 필요한 말은 "채점 서버가 고장났어요"이고,
    # 그건 채점 응답의 status가 이미 프론트에 전달한다(JUDGE_LABELS.INTERNAL_ERROR).
    #
    # consecutive_error_count 쪽은 features.py가 이미 막았지만(SYSTEM_STATUSES),
    # R7(90초 무진전 + 실행 2회)은 그것만으로는 막히지 않는다 -- 채점기가 죽어
    # 있으면 진전이 없는 게 당연하므로 시간이 흐르는 것만으로 발화한다.
    #
    # R0(도움 요청)보다는 아래다: 학생이 직접 물었으면 채점기 상태와 무관하게 답한다.
    if last is not None and last.status in SYSTEM_STATUSES:
        return (
            ProcessStatus.PROGRESSING,
            None,
            "채점 서버에 문제가 생겨 학습 상태를 판단할 수 없습니다.",
        )

    # R2 이해 불확실 -- agent_plan §14 시나리오 C (대규모 재작성 -> 즉시 통과)
    #
    # **진전 가드보다 위에 있어야 한다.** 3/5 -> 5/5는 progress_delta=+2라 R3가
    # 먼저 잡아버리는데, 이 시나리오의 요점이 바로 "겉보기 진전이 의심스러운 경우"다.
    # backend_plan §12의 규칙 나열도 이 순서다 (UNDERSTANDING_UNCERTAIN이 progress_delta 앞).
    # 진전 가드가 보호해야 할 대상은 2/5 -> 3/5 -> 4/5로 기어오르는 학생이지,
    # 재작성을 붙여넣고 5/5로 점프한 학생이 아니다.
    if (
        last is not None
        and last.status is JudgeStatus.ACCEPTED
        and f.large_change_detected
    ):
        return (
            ProcessStatus.UNDERSTANDING_UNCERTAIN,
            TriggerType.UNDERSTANDING_UNCERTAIN,
            "대규모 코드 변경 직후 통과해 이해 근거가 불충분합니다.",
        )

    # R3 진전 가드 -- backend_plan §22 시나리오 1 (2/5 -> 3/5 -> 4/5)
    if f.progress_delta > 0 or f.improved_recently:
        return (
            ProcessStatus.PROGRESSING,
            None,
            "테스트 결과가 개선되고 있어 개입하지 않습니다.",
        )

    # R4 해결됨
    if last is not None and last.status is JudgeStatus.ACCEPTED:
        return ProcessStatus.PROGRESSING, None, "문제를 통과했습니다."

    # R5 반복 실패 -- backend_plan §22 시나리오 2
    if (
        f.same_result_count >= cfg.same_result_threshold
        and f.same_region_edit_count >= cfg.same_region_threshold
    ):
        return (
            ProcessStatus.STUCK,
            TriggerType.REPEATED_FAILURE,
            "같은 코드 영역을 반복 수정했지만 테스트 결과가 동일합니다.",
        )

    # R5b 편집 없이 반복 실행.
    # backend_plan §12의 문자 그대로의 규칙이 놓치는 케이스다: 아무것도 안 고치고 Run만 3번이면
    # same_region_edit_count가 0이라 R5가 안 걸리는데, 동일 코드 3연속 실행은 명백히 stuck이다.
    if f.same_result_count >= cfg.same_result_threshold and f.edits_in_result_streak == 0:
        return (
            ProcessStatus.STUCK,
            TriggerType.REPEATED_FAILURE,
            "코드를 수정하지 않은 채 같은 결과를 반복해서 확인하고 있습니다.",
        )

    # R6 연속 에러
    if f.consecutive_error_count >= cfg.consecutive_error_threshold:
        return (
            ProcessStatus.STUCK,
            TriggerType.REPEATED_FAILURE,
            "실행 오류가 연속으로 발생하고 있습니다.",
        )

    # R7 무진전
    if (
        f.seconds_without_progress >= cfg.no_progress_seconds
        and f.attempt_count >= 2
    ):
        return (
            ProcessStatus.POSSIBLE_STUCK,
            TriggerType.NO_PROGRESS,
            f"{f.seconds_without_progress}초 동안 테스트 결과에 진전이 없습니다.",
        )

    # ------------------------------------------------------------------
    # R7b/R7c: **편집만으로** 발화하는 규칙.
    #
    # 여기 위의 규칙(R1s~R7)은 전부 TEST_RESULT를 요구한다 -- attempt_count도
    # RUN/SUBMIT 이벤트가 아니라 서버가 채점하며 쓰는 결과만 센다. 그래서 학생이
    # 실행/제출을 한 번도 누르지 않으면 R0(도움 요청) 말고는 발화할 수 있는 규칙이
    # 없었다. 붙여넣기도 churn도 feature로는 이미 잡히는데 쓰는 규칙이 없었다.
    #
    # 두 규칙 모두 **신호 2개**를 요구한다. 하나만으로는 오탐이 많다 --
    # "유휴 45초"는 그냥 문제를 읽는 중일 수도 있고, "큰 변경"은 빠르게 타이핑한
    # 것일 수도 있다. 여기에 "그리고 손을 놓았다"가 겹쳐야 개입할 만한 상황이 된다.
    #
    # 그리고 둘 다 edits_since_last_trigger >= 1을 요구한다: 지난번에 찔렀는데
    # 학생이 코드를 건드리지도 않았으면 또 찌를 이유가 없다. cooldown(30초 또는
    # 다음 Run)만으로는 이걸 막을 수 없다 -- 편집만 하는 세션에는 Run이 영영
    # 오지 않아서 30초마다 같은 트리거가 반복된다.
    edited_since_last_nudge = f.edits_since_last_trigger >= 1

    # R7b 붙여넣기 후 검증 없음 -> 이해도 확인 분기.
    # R2와 같은 trigger를 쓴다: R2는 "붙여넣고 **통과**했다", 이건 "붙여넣고
    # 실행조차 안 했다"로 상황은 다르지만, agent가 받아야 할 지시는 같다
    # ("정답을 주지 말고 왜 이렇게 동작하는지 설명하게 하라").
    # 새 TriggerType을 만들면 agent 쪽 분기(backend_adapter의 이해도 확인 매핑)를
    # 같이 고쳐야 하는데, 그럴 만큼 다른 상황이 아니다.
    if (
        f.large_change_unverified
        and f.seconds_since_last_edit >= cfg.paste_settle_seconds
        and edited_since_last_nudge
    ):
        return (
            ProcessStatus.UNDERSTANDING_UNCERTAIN,
            TriggerType.UNDERSTANDING_UNCERTAIN,
            "대규모 코드 변경 후 실행 없이 멈춰 있어 이해 여부를 확인해야 합니다.",
        )

    # R7c 편집 정체: 같은 영역만 반복해서 고치다가 손을 놓았다.
    # 여기서도 "아직 안 돌려본 편집"을 요구한다 -- 고친 뒤 실행해서 결과를 본
    # 학생은 R5/R6가 다룰 문제이지 편집 정체가 아니다.
    if (
        f.same_region_edit_count >= cfg.edit_churn_threshold
        and f.seconds_since_last_edit >= cfg.idle_edit_seconds
        and f.edits_since_last_result >= 1
        and edited_since_last_nudge
    ):
        return (
            ProcessStatus.POSSIBLE_STUCK,
            TriggerType.NO_PROGRESS,
            f"같은 영역을 {f.same_region_edit_count}번 고치다가 "
            f"{f.seconds_since_last_edit}초째 멈춰 있습니다.",
        )

    # R7d 완전 무활동: 편집도 실행도 없이 그냥 손을 놓았다.
    #
    # R7c와 무엇이 다른가. R7c는 "같은 영역 churn 3회 + 편집 멈춤"이라 **고치다가**
    # 멈춘 학생만 잡는다. 한 줄 쓰고 멍하니 있는 학생, 실행 한 번 하고 결과를 보다가
    # 멈춘 학생은 어떤 규칙에도 걸리지 않아 영원히 침묵했다. 이 규칙이 그 구멍이다.
    #
    # 임계값을 10초까지 짧게 잡을 수 있는 근거는 anti-spam 가드 쪽이다:
    # activity_since_last_trigger >= 1 이므로 **한 유휴 구간에서 최대 한 번** 발화한다.
    # (개입 후 학생이 아무 반응도 하지 않으면 cooldown이 풀려도 다시 찌르지 않는다.
    #  AGENT_TRIGGER/AGENT_INTERVENTION은 활동으로 세지 않으므로 카운터가 0에 머문다.)
    #
    # 여기가 R8 위여야 하는 이유: R8은 attempt>=2면 trigger 없이 PRODUCTIVE_STRUGGLE로
    # 끝내버린다. 아래에 두면 실행을 2번 이상 한 학생에게는 무활동 규칙이 죽는다.
    # 반대로 R3(진전 가드)/R4(통과) 아래에 두는 것은 의도적이다 -- 개선 중이거나
    # 이미 통과한 학생을 10초 침묵만으로 찌르지 않는다.
    #
    # idle_no_activity_seconds=0은 **규칙을 끈다.** 무활동 개입은 교수자 취향이
    # 갈리는 지점이고(생각할 시간을 주고 싶은 수업이 있다), 다른 임계값과 달리
    # "아주 크게 잡기"로는 끌 수 없다 -- 값이 크면 오래 자리를 비운 학생에게
    # 돌아오는 순간 뒤늦은 개입이 튀어나온다.
    if (
        cfg.idle_no_activity_seconds > 0
        and f.seconds_since_last_activity >= cfg.idle_no_activity_seconds
        and f.activity_since_last_trigger >= 1
    ):
        return (
            ProcessStatus.POSSIBLE_STUCK,
            TriggerType.NO_PROGRESS,
            f"{f.seconds_since_last_activity}초 동안 아무 활동이 없어 "
            "막혀 있을 가능성이 있습니다.",
        )

    # R8 생산적 고전.
    # same_result_count 가드를 걸지 않는다: 진짜로 막힌 경우는 R5/R5b/R6가 이미 위에서
    # 다 잡았다. 여기까지 내려온 학생은 "같은 점수지만 서로 다른 영역을 시도 중"이고,
    # 그게 정확히 agent_plan §3.1의 PRODUCTIVE_STRUGGLE 정의다.
    # (가드를 걸면 이 학생이 R9로 떨어져 PROGRESSING으로 잘못 표시된다.)
    if f.attempt_count >= 2:
        return (
            ProcessStatus.PRODUCTIVE_STRUGGLE,
            None,
            "다양한 시도를 하고 있어 스스로 해결할 여지가 있습니다.",
        )

    # R9 기본. 실행이 0~1회라 아직 판단할 증거가 없다.
    return (
        ProcessStatus.PROGRESSING,
        None,
        "개입이 필요한 신호가 아직 없습니다.",
    )


def decide(
    f: ProcessFeatures,
    *,
    now: datetime,
    cooldown_active: bool,
    cooldown_remaining: int,
    hint_pending: bool,
    cfg: MonitorConfig | None = None,
) -> ProcessState:
    """순수 판정 함수. DB를 모른다 -- 테스트가 feature만 넘겨 호출할 수 있다."""
    cfg = cfg or DEFAULT_MONITOR_CONFIG
    evidence = _evidence(f, cfg)

    # R0 도움 요청 -- cooldown을 무시한다.
    # "도와줘"를 눌렀는데 침묵하는 건 데모 킬러이고, 명시적 요청은 어떤 휴리스틱보다
    # 강한 신호다. hint_pending(= 마지막 AGENT_TRIGGER보다 나중의 HINT_REQUEST)이라는
    # 조건이 anti-spam 가드다: 없으면 힌트 클릭 한 번이 이후 모든 평가에서 영원히 재발화한다.
    if hint_pending:
        return ProcessState(
            status=ProcessStatus.HELP_REQUESTED,
            trigger=TriggerType.HELP_REQUESTED,
            reason="학생이 직접 도움을 요청했습니다.",
            evidence=evidence,
            cooldown_active=cooldown_active,
            cooldown_remaining_seconds=cooldown_remaining,
            features=f,
            evaluated_at=now,
        )

    status, trigger, reason = _classify(f, cfg)

    # R1 cooldown 게이트: status는 그대로 분류하되 trigger만 죽인다.
    # 데모에서 중요한 성질이다 -- 심사위원은 시스템이 stuck임을 *알면서도*
    # 다시 끼어들지 않기로 *선택*했다는 걸 본다.
    if cooldown_active and trigger is not None:
        trigger = None
        reason = f"{reason} (직전 개입 후 {cooldown_remaining}초 대기 중)"

    return ProcessState(
        status=status,
        trigger=trigger,
        reason=reason,
        evidence=evidence,
        cooldown_active=cooldown_active,
        cooldown_remaining_seconds=cooldown_remaining,
        features=f,
        evaluated_at=now,
    )


# --------------------------------------------------------------------- 진입점


def evaluate(
    db: DbSession,
    session_id: str,
    *,
    now: datetime | None = None,
    cfg: MonitorConfig | None = None,
) -> ProcessState:
    """순수 판정. **아무것도 쓰지 않는다.** 폴링해도 안전하다."""
    cfg = cfg or DEFAULT_MONITOR_CONFIG
    now = now or utcnow()

    session = store.require_session(db, session_id)
    events = trace_service.all_events(db, session_id)
    snapshots = store.all_snapshots(db, session_id)
    f = extract_features(
        db, session_id, now=now, cfg=cfg, session=session, events=events, snapshots=snapshots
    )

    has_result_after_trigger = f.last_trigger_seq is not None and any(
        EventType(e.type) is EventType.TEST_RESULT and e.seq > f.last_trigger_seq
        for e in events
    )
    cooldown_active, remaining = _cooldown(f, has_result_after_trigger, now, cfg)

    hint_pending = f.last_hint_seq is not None and (
        f.last_trigger_seq is None or f.last_hint_seq > f.last_trigger_seq
    )

    return decide(
        f,
        now=now,
        cooldown_active=cooldown_active,
        cooldown_remaining=remaining,
        hint_pending=hint_pending,
        cfg=cfg,
    )


def evaluate_and_record(
    db: DbSession,
    session: Session,
    *,
    now: datetime | None = None,
    cfg: MonitorConfig | None = None,
) -> ProcessState:
    """evaluate() 후 trigger가 있으면 AGENT_TRIGGER 이벤트를 기록한다."""
    now = now or utcnow()
    state = evaluate(db, session.id, now=now, cfg=cfg)
    if state.trigger is None:
        return state

    trace_service.append_event(
        db,
        session_id=session.id,
        type=EventType.AGENT_TRIGGER,
        source=EventSource.SERVER,
        payload={
            "trigger": state.trigger.value,
            "status": state.status.value,
            "reason": state.reason,
            "evidence": state.evidence,
            # 그 순간의 feature를 통째로 스냅샷한다. 사후에 "왜 이 숫자로 호출됐는지"를
            # 정확히 설명할 수 있다 -- backend_plan §18이 발표용으로 요구하는 것.
            "features": features_to_dict(state.features),
        },
        code_version=session.last_code_version or None,
        at=now,
    )
    db.commit()
    return state


def features_to_dict(f: ProcessFeatures) -> dict:
    """JSON 직렬화 가능한 형태로. datetime과 dataclass를 평평하게 만든다."""
    last = f.last_result
    return {
        "elapsed_seconds": f.elapsed_seconds,
        "run_count": f.run_count,
        "submit_count": f.submit_count,
        "attempt_count": f.attempt_count,
        "recent_scores": f.recent_scores,
        "same_result_count": f.same_result_count,
        "progress_delta": f.progress_delta,
        "improved_recently": f.improved_recently,
        "seconds_without_progress": f.seconds_without_progress,
        "same_region_edit_count": f.same_region_edit_count,
        "repeated_edit_region": f.repeated_edit_region,
        "edits_since_progress": f.edits_since_progress,
        "edits_in_result_streak": f.edits_in_result_streak,
        "undo_count": f.undo_count,
        "hint_count": f.hint_count,
        "large_change_detected": f.large_change_detected,
        "recent_error_types": f.recent_error_types,
        "consecutive_error_count": f.consecutive_error_count,
        "snapshot_count": f.snapshot_count,
        "seconds_since_last_edit": f.seconds_since_last_edit,
        "seconds_since_last_activity": f.seconds_since_last_activity,
        "edits_since_last_trigger": f.edits_since_last_trigger,
        "activity_since_last_trigger": f.activity_since_last_trigger,
        "edits_since_last_result": f.edits_since_last_result,
        "large_change_unverified": f.large_change_unverified,
        "last_result": None
        if last is None
        else {
            "mode": last.mode,
            "status": last.status.value,
            "passed": last.passed,
            "total": last.total,
        },
    }
