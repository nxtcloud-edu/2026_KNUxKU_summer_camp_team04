"""tutor_agent를 별도 프로세스로 노출하는 얇은 HTTP 서비스.

왜 in-process가 아니라 HTTP인가
-------------------------------
`backend_adapter.TutorAgentAdapter`를 backend 프로세스 안에서 직접 쓰려면
backend venv에 `strands-agents`를 설치해야 하는데, **이게 불가능하다**:

    strands-agents 1.52.0  ->  starlette 1.6.0 을 끌어온다
    backend  fastapi 0.115.6 ->  starlette<0.42.0 을 요구한다

두 조건은 동시에 만족될 수 없다 (실제로 설치해서 확인함 — backend가 깨진다).
`PYTHONPATH`만 넘겨서 소스만 보이게 하면 import 자체는 성공하지만, 첫
`decide()`에서 `ModuleNotFoundError: No module named 'strands'`가 나고
어댑터의 폴백에 걸려 **항상 WAIT**만 반환한다 (= 사실상 미연결).

그래서 agent를 **자기 venv를 가진 별도 프로세스**로 띄우고, backend는
`http_client.HttpAgentClient`로 HTTP 호출만 한다. judge가 `main.py`로 자기
로직을 감싸 노출하는 것과 같은 패턴이다.

이 파일은 **얇다.** 판단 로직은 전부 `backend_adapter.TutorAgentAdapter`에
있고 (backend 담당자가 작성/테스트한 코드), 여기서는 JSON <-> 그 어댑터를
연결만 한다. 어댑터가 이미 dict를 duck typing으로 받고 어떤 경우에도 예외를
던지지 않으므로, 변환 코드가 거의 필요 없다.

실행:
    cd agent
    python -m uvicorn tutor_agent.service:app --port 8100
    # (agent/src 가 sys.path에 있어야 한다 — pip install -e . 또는 PYTHONPATH=src)
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import BackgroundTasks, FastAPI
from pydantic import BaseModel, Field

from .backend_adapter import get_backend_agent
from .schemas import ReviewRequest, ValidationReport

log = logging.getLogger(__name__)

# uvicorn은 자기 로거(uvicorn/uvicorn.access/uvicorn.error)만 설정하고 앱 로거는
# 안 건드린다. basicConfig를 안 하면 루트 로거에 핸들러가 없어서 Python의
# "handler of last resort"가 WARNING 이상만 stderr로 흘려보낸다 — 그러면
# `/decide`의 log.info("evaluation(백그라운드): ...")가 조용히 사라진다
# (실제로 겪음: 백그라운드 태스크는 돌고 있는데 로그가 하나도 안 보였음).
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

#: backend가 기본으로 찾아오는 포트. 8000(backend) / 5173(frontend)과 겹치지 않게.
DEFAULT_PORT = 8100

app = FastAPI(title="CodeTrace Tutor Agent Service")


class DecideRequest(BaseModel):
    """`backend/app/agent/interface.py::AgentContext`를 그대로 받는다.

    필드명이 backend와 한 글자라도 다르면 연결이 조용히 깨진다
    (`backend_adapter.AgentContext` 미러와 같은 계약 —
    `tests/test_backend_adapter.py`가 backend 소스를 텍스트로 읽어 드리프트를 검사한다).

    전 필드에 기본값을 준다. backend가 필드를 하나 추가해도 여기서 422로
    떨어뜨리지 않고 WAIT로 흘러가게 하기 위함이다 (agent 실패가 채점 응답을
    깨뜨리면 안 된다 — backend_plan §14).
    """

    session_id: str = ""
    problem: dict[str, Any] = Field(default_factory=dict)
    current_code: str = ""
    current_code_version: int = 0
    judge_result: dict[str, Any] | None = None
    recent_trace: list[str] = Field(default_factory=list)
    features: dict[str, Any] = Field(default_factory=dict)
    process_status: str = ""
    trigger: str | None = None
    evidence: list[str] = Field(default_factory=list)
    previous_interventions: list[dict[str, Any]] = Field(default_factory=list)

    model_config = {"extra": "allow"}  # backend가 필드를 늘려도 422로 죽지 않는다


class DecideResponse(BaseModel):
    """`backend/app/agent/interface.py::AgentDecision` 미러.

    `action`은 문자열로 내보낸다 (`"WAIT"` / `"HINT"` / ...). backend 쪽
    클라이언트가 자기 enum으로 되돌린다.
    """

    state: str
    concept: str | None = None
    action: str
    reason: str
    activity: dict[str, Any] | None = None


@app.get("/health")
def health() -> dict:
    """backend가 이 서비스가 살아있는지 확인하는 용도.

    LLM 프로바이더까지 검사하지는 않는다 (그건 호출당 비용이 든다).
    프로세스가 떠 있으면 ok다.
    """
    return {"status": "ok", "service": "tutor_agent", "agent": get_backend_agent().name}


@app.post("/decide", response_model=DecideResponse)
def decide(request: DecideRequest, background_tasks: BackgroundTasks) -> DecideResponse:
    """Monitor가 개입 시점이라고 판단했을 때 backend가 부르는 단일 진입점.

    `TutorAgentAdapter.decide_with_pipeline_result()`는 **어떤 경우에도 예외를
    던지지 않고** 실패를 WAIT로 흘린다. 그래서 이 핸들러도 5xx를 내지 않는다
    — backend는 항상 파싱 가능한 결정을 받는다 (네트워크 자체가 끊긴 경우만
    클라이언트 쪽 폴백이 담당한다).

    evaluation은 응답을 반환한 **뒤에** 백그라운드로 돌린다 (`orchestrator.py`가
    더 이상 동기로 부르지 않는 이유 참고 — 학생에게 보여줄 결정에 영향이
    없는데 30초 파이프라인의 1/4을 더 기다리게 할 이유가 없다). 지금은 결과를
    로그로만 남긴다 — 저장할 곳(분석 DB 등)이 아직 backend에 없어서다. 그게
    생기면 `_log_evaluation`을 그쪽으로 보내는 걸로 바꾸면 된다.
    """
    decision, pipeline_context = get_backend_agent().decide_with_pipeline_result(
        request.model_dump()
    )
    if pipeline_context is not None:
        session_ctx, result = pipeline_context
        if result.action_plan is not None:
            background_tasks.add_task(_log_evaluation, session_ctx, result.action_plan)

    return DecideResponse(
        state=decision.state,
        concept=decision.concept,
        # AgentAction은 str Enum이라 .value가 backend enum 값과 글자 그대로 같다.
        action=decision.action.value,
        reason=decision.reason,
        activity=decision.activity,
    )


def _log_evaluation(session_ctx: Any, action_plan: Any) -> None:
    """방금 반환한 결정을 백그라운드에서 평가해 로그로 남긴다.

    응답 경로 밖에서 실행되므로 여기서 걸리는 시간은 학생 대기 시간에
    전혀 들어가지 않는다. 실패해도 아무 데도 영향 없음 — 로그만 남는다.
    """
    # 지연 import: 이 백그라운드 작업이 안 걸리면 evaluation_agent(=strands 호출)를
    # import 시점에 끌어오지 않는다.
    from .agents import evaluation_agent

    try:
        evaluation = evaluation_agent.evaluate(session_ctx, action_plan)
        log.info(
            "evaluation(백그라운드): score=%.2f follow_up_needed=%s notes=%s",
            evaluation.effectiveness_score,
            evaluation.follow_up_needed,
            evaluation.notes,
        )
    except Exception:
        log.exception("백그라운드 evaluation 실패 (응답에는 영향 없음)")


@app.post("/generate-problem", response_model=ValidationReport)
def generate_problem(request: ReviewRequest) -> ValidationReport:
    """오답/복습 기반으로 새 문제를 생성한다 (judge 검증까지 통과한 것만).

    `/decide`와 달리 이건 실시간 개입 경로가 아니다 — 학생이 문제를 다 푼 뒤,
    또는 복습 큐를 채울 때 호출한다고 가정한다. LLM 생성 + judge 샌드박스
    실행이라 수 초~수십 초가 걸릴 수 있으므로, backend는 이 호출을 채점 응답
    경로에 끼워넣지 말 것.

    아직 어떤 호출자도 없다 (backend에 복습 큐가 생기면 그때 연결). 지금
    노출해두는 이유는, 나중에 이걸 추가하려고 서비스 구조를 다시 손대지
    않기 위해서다.

    응답의 `problem_json`은 judge의 `problems/*.json`과 같은 스키마다
    (`problem_id`는 저장 시점에 호출자가 부여한다).
    """
    # 지연 import: 이 엔드포인트를 안 쓰면 strands/judge를 건드리지 않는다.
    from .agents.problem_generator_agent import generate

    try:
        return generate(request)
    except Exception as exc:  # noqa: BLE001 - 어떤 실패든 500 대신 구조화된 실패로 돌려준다
        log.exception("문제 생성 실패")
        return ValidationReport(is_valid=False, error_message=f"문제 생성에 실패했습니다: {exc}")
