"""모든 enum. 순환 import를 피하기 위해 한 파일에 모은다.

Event 타입 계약 (backend_plan/feature_plan/frontend_plan 3개 문서 충돌 해소)
------------------------------------------------------------------------
해소 규칙:
  1. backend_plan이 기본 승리. DB 컬럼/agent 계약/monitor 입력의 최심층 의존성이라
     이름을 바꾸는 비용이 가장 크다.
  2. frontend_plan의 이름이 "누가 보냈는가"만 인코딩하면 backend_plan 이름을 쓰고
     구분은 `source` 컬럼으로 옮긴다. RUN vs RUN_REQUESTED는 의미 차이가 아니라
     provenance 차이이고, provenance는 타입 이름이 아니라 필드에 속한다.
     (둘 다 두면 모든 feature/monitor 규칙이 영원히 두 이름을 매칭해야 한다.)
  3. 2/3 문서가 합의하면 짧은 쪽.

  CODE_CHANGE                -> CODE_SNAPSHOT       (2/3 합의, 저장 산출물의 이름)
  RUN_REQUESTED/SUBMIT_...   -> RUN / SUBMIT        (provenance는 source 컬럼)
  LEARNING_ACTIVITY_RESPONSE -> ACTIVITY_RESPONSE   (2/3 합의, 짧음)
  ACTIVITY_OPENED            -> 유지                (timeline이 필요로 함)
"""
from __future__ import annotations

from enum import Enum


class SessionStatus(str, Enum):
    SOLVING = "SOLVING"
    FINISHED = "FINISHED"


class EventSource(str, Enum):
    """이벤트를 만든 주체. RUN vs RUN_REQUESTED의 구분이 여기로 왔다."""

    CLIENT = "CLIENT"  # 브라우저가 보낸 사용자 행동
    CLIENT_JUDGE = "CLIENT_JUDGE"  # 브라우저 Pyodide 채점 결과 (오늘의 경로)
    SERVER = "SERVER"  # 서버 생성 (SESSION_START, AGENT_TRIGGER, Docker judge)


class EventType(str, Enum):
    # --- 클라이언트가 보낼 수 있음 ---
    CODE_SNAPSHOT = "CODE_SNAPSHOT"
    RUN = "RUN"
    SUBMIT = "SUBMIT"
    UNDO = "UNDO"
    RESET = "RESET"
    HINT_REQUEST = "HINT_REQUEST"
    ACTIVITY_OPENED = "ACTIVITY_OPENED"
    ACTIVITY_RESPONSE = "ACTIVITY_RESPONSE"
    SESSION_END = "SESSION_END"

    # --- 서버만 생성 ---
    SESSION_START = "SESSION_START"
    TEST_RESULT = "TEST_RESULT"
    SYNTAX_ERROR = "SYNTAX_ERROR"  # 예약. 아래 주석 참조
    RUNTIME_ERROR = "RUNTIME_ERROR"  # 예약. 아래 주석 참조
    AGENT_TRIGGER = "AGENT_TRIGGER"
    AGENT_INTERVENTION = "AGENT_INTERVENTION"


# SYNTAX_ERROR / RUNTIME_ERROR는 enum에 **예약만** 하고 지금은 아무것도 emit하지 않는다.
# judge 경로는 TEST_RESULT 이벤트를 정확히 1개 쓰고, 상태는 payload.status가 운반한다.
# 한 번의 실행이 두 행을 만들면 recent_error_types를 계산할 지점이 둘이 된다.
# 타임라인 렌더러가 TEST_RESULT{status: SYNTAX_ERROR}를 kind="ERROR"로 표시하므로
# 데모 화면은 동일하고 데이터의 진실은 하나다.


class ClientEventType(str, Enum):
    """요청 스키마 전용 축소 enum.

    EventIn.type을 이 타입으로 선언하면 {"type": "TEST_RESULT"}는 핸들러 진입 전에
    Pydantic이 422로 막는다. 런타임 403 체크보다 나은 이유:
    선언적이고, OpenAPI 스키마에 제약이 드러나 프론트의 생성 타입이 표현조차 못 하며,
    새 엔드포인트를 추가할 때 잊어버릴 수가 없다.
    """

    CODE_SNAPSHOT = "CODE_SNAPSHOT"
    RUN = "RUN"
    SUBMIT = "SUBMIT"
    UNDO = "UNDO"
    RESET = "RESET"
    HINT_REQUEST = "HINT_REQUEST"
    ACTIVITY_OPENED = "ACTIVITY_OPENED"
    ACTIVITY_RESPONSE = "ACTIVITY_RESPONSE"
    SESSION_END = "SESSION_END"


CLIENT_EVENT_TYPES: frozenset[EventType] = frozenset(
    EventType(t.value) for t in ClientEventType
)
SERVER_ONLY_EVENT_TYPES: frozenset[EventType] = frozenset(EventType) - CLIENT_EVENT_TYPES


class JudgeStatus(str, Enum):
    ACCEPTED = "ACCEPTED"
    WRONG_ANSWER = "WRONG_ANSWER"
    RUNTIME_ERROR = "RUNTIME_ERROR"
    SYNTAX_ERROR = "SYNTAX_ERROR"
    TIME_LIMIT = "TIME_LIMIT"
    INTERNAL_ERROR = "INTERNAL_ERROR"


# 점수로 셀 수 있는 결과 vs 셀 수 없는 결과.
# features.py의 가장 중요한 정의: 에러 결과는 0점이 아니라 **관측 없음**이다.
SCORED_STATUSES: frozenset[JudgeStatus] = frozenset(
    {JudgeStatus.ACCEPTED, JudgeStatus.WRONG_ANSWER}
)
ERROR_STATUSES: frozenset[JudgeStatus] = frozenset(JudgeStatus) - SCORED_STATUSES


class ProcessStatus(str, Enum):
    PROGRESSING = "PROGRESSING"
    PRODUCTIVE_STRUGGLE = "PRODUCTIVE_STRUGGLE"
    POSSIBLE_STUCK = "POSSIBLE_STUCK"
    STUCK = "STUCK"
    UNDERSTANDING_UNCERTAIN = "UNDERSTANDING_UNCERTAIN"
    HELP_REQUESTED = "HELP_REQUESTED"


class TriggerType(str, Enum):
    HELP_REQUESTED = "HELP_REQUESTED"
    REPEATED_FAILURE = "REPEATED_FAILURE"
    NO_PROGRESS = "NO_PROGRESS"
    UNDERSTANDING_UNCERTAIN = "UNDERSTANDING_UNCERTAIN"


class RegionTag(str, Enum):
    """코드 영역 태그.

    accumulator는 backend_plan §10의 3개(loop/condition/initialization)를 넘는 추가분이다.
    대표 데모 문제가 accumulator 루프이고, "accumulator 영역 ×3 수정"이
    심사위원에게 "other ×3"보다 훨씬 나은 근거 문자열이기 때문.
    """

    LOOP = "loop"
    CONDITION = "condition"
    ACCUMULATOR = "accumulator"
    INITIALIZATION = "initialization"
    RETURN = "return"
    FUNCTION_DEF = "function_def"
    OTHER = "other"


class AgentAction(str, Enum):
    WAIT = "WAIT"
    HINT = "HINT"
    TRACE = "TRACE"
    PREDICT = "PREDICT"
    DEBUG = "DEBUG"
    VERIFY = "VERIFY"
