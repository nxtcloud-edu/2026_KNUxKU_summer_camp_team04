"""LLM 호출을 **하나의 영속 이벤트 루프**에서 실행하는 런타임.

왜 이 파일이 필요한가 (`RuntimeError: Event loop is closed`)
------------------------------------------------------------
`agent.structured_output(...)`(동기 API)는 strands 내부에서 이렇게 동작한다
(`strands/_async.py::run_async`):

    def execute():
        return asyncio.run(execute_async())      # <- 호출마다 새 이벤트 루프
    with ThreadPoolExecutor() as executor:
        return executor.submit(context.run, execute).result()

즉 **호출 한 번마다 새 스레드 + 새 이벤트 루프를 만들고, 끝나면 루프를 닫는다.**

반면 `models.get_model()`이 만드는 `AnthropicModel`은 생성 시점에
`anthropic.AsyncAnthropic`(내부에 `httpx.AsyncClient` 연결 풀)을 **한 번** 만들어
계속 들고 있고, 우리는 그 모델을 얹은 `Agent`를 `TutorPipeline.__init__`에서
캐시해 프로세스 내내 재사용한다 (`backend_adapter.get_backend_agent()`가
`lru_cache` 싱글턴이므로 파이프라인도 하나뿐이다).

httpx/anyio의 연결 풀과 동기화 프리미티브는 **처음 사용된 이벤트 루프에 묶인다.**
그래서 다른 루프에서 그 커넥션을 재사용하려 하면 터진다:

    RuntimeError: Event loop is closed
      ... httpx/_transports/default.py aclose()
      ... anyio/_backends/_asyncio.py aclose()

**진짜 방아쇠는 동시 요청이다.** 관찰된 로그를 보면 `/decide` 두 개가 겹쳐
처리되고 있었다:

    Tool #3: StudentState
    Tool #4: StudentState        <- 다른 요청
    Tool #3: GuidedAction
    INFO: 127.0.0.1:51533 - "POST /decide HTTP/1.1" 200 OK
    INFO: 127.0.0.1:51527 - "POST /decide HTTP/1.1" 200 OK

FastAPI는 `def`(sync) 엔드포인트를 워커 스레드풀에서 돌린다. 즉 두 요청이 각자
`asyncio.run`으로 **서로 다른 이벤트 루프**를 만들면서 캐시된 하나뿐인 httpx
풀을 동시에 쓴다. 한쪽 루프가 닫히면 그 풀에 남은 커넥션은 닫힌 루프를 참조한
채로 남고, 다른 쪽이 그걸 집어들면 위 예외가 난다.

실측 (캐시된 `Agent` 하나를 4스레드가 공유, Anthropic 다이렉트 API):

| 호출 방식 | 결과 |
|---|---|
| `agent.structured_output()` | 1라운드(4회) 성공 후 **2라운드에서 무한 대기** (7분 넘게 진행 없음) |
| 이 모듈의 `structured_output()` | 3라운드 12회 **전부 성공**, 75초 이내 완료 |

즉 증상은 두 갈래로 나온다 — 예외(`Event loop is closed`)로 터지거나, 아예
**멈춘다.** 둘의 원인은 같다.

실제 피해는 더 컸다. 이 예외는 `state_agent.assess()` → `TutorPipeline.run()`을
거쳐 `backend_adapter.decide_with_pipeline_result()`의 `except Exception`에
삼켜지고 **WAIT 폴백**이 된다 (멈추는 경우는 backend의 읽기 타임아웃 30초가
끊고 역시 WAIT). WAIT은 개입으로 기록되지 않으므로
(`backend/app/judge/router.py`), 학생에게는 "힌트가 그냥 안 나온다"로만 보이고
원인은 agent 서비스 stderr에만 남는다.

해결
----
루프를 호출마다 만들지 않는다. **프로세스에 하나뿐인 데몬 스레드가 이벤트
루프를 계속 살려두고**, 모든 LLM 호출을 `asyncio.run_coroutine_threadsafe`로
그 루프에 밀어넣는다. 클라이언트가 처음 묶인 루프가 영원히 살아 있으므로 위
충돌 자체가 생기지 않는다.

부수 효과로 얻는 것:

* **연결 재사용.** 호출마다 TCP/TLS 핸드셰이크를 다시 하지 않는다.
* **진짜 동시성.** 여러 요청이 같은 루프에서 인터리브되므로, LLM 대기(I/O)가
  겹칠 때 서로를 막지 않는다 (위 실측: 4스레드 동시 호출이 전부 통과). 스레드마다
  루프를 새로 만드는 기존 방식은 요청마다 스레드가 늘어나면서 풀만 망가뜨렸다.
* **파일 디스크립터 누수 차단.** 예전 코드는 백그라운드 evaluation처럼 매번
  새 `Agent`(=새 httpx 클라이언트)를 만들고 닫지 않아 fd가 계속 늘었다.

주의: strands `Agent.structured_output_async()`는 `self.messages`를 건드리지
않고 `temp_messages`를 따로 만들어 호출하므로, 캐시된 `Agent`를 여러 요청이
공유해도 대화 이력이 섞이지 않는다 (그래서 이 파일이 동시성을 열어도 안전하다).
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import os
import threading
from concurrent.futures import TimeoutError as FutureTimeoutError
from typing import Any, TypeVar

log = logging.getLogger(__name__)

T = TypeVar("T")

#: 한 번의 LLM 호출을 이 시간(초)까지만 기다린다. 초과하면 취소하고 예외를
#: 던져서 호출부(어댑터)가 WAIT으로 폴백하게 한다 — 영속 루프에 영원히 매달린
#: 코루틴이 쌓이는 것보다 낫다. backend의 읽기 타임아웃(기본 30초)보다 길게
#: 두는 게 맞다: 여기서 먼저 끊으면 backend는 어차피 이미 포기한 상태다.
DEFAULT_CALL_TIMEOUT_SECONDS = 120.0


def _call_timeout() -> float:
    raw = os.getenv("LLM_CALL_TIMEOUT_SECONDS")
    if not raw:
        return DEFAULT_CALL_TIMEOUT_SECONDS
    try:
        return float(raw)
    except ValueError:
        log.warning(
            "LLM_CALL_TIMEOUT_SECONDS=%r 를 숫자로 읽지 못해 기본값 %s초를 씁니다.",
            raw,
            DEFAULT_CALL_TIMEOUT_SECONDS,
        )
        return DEFAULT_CALL_TIMEOUT_SECONDS


class _PersistentLoop:
    """데몬 스레드에서 계속 돌아가는 이벤트 루프 하나.

    지연 생성한다 — LLM을 한 번도 부르지 않는 프로세스(예: 테스트, 문제 생성만
    쓰는 경로)가 쓸데없이 스레드를 띄우지 않도록.
    """

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._lock = threading.Lock()

    def _ensure(self) -> asyncio.AbstractEventLoop:
        loop = self._loop
        if loop is not None and not loop.is_closed():
            return loop

        with self._lock:
            # 락을 잡는 동안 다른 스레드가 이미 만들었을 수 있다.
            loop = self._loop
            if loop is not None and not loop.is_closed():
                return loop

            loop = asyncio.new_event_loop()
            thread = threading.Thread(
                target=self._run_forever,
                args=(loop,),
                name="tutor-agent-llm-loop",
                # 데몬으로 둔다: uvicorn이 종료될 때 이 스레드가 프로세스를
                # 붙잡고 있으면 안 된다 (Ctrl+C가 안 먹는 서버가 된다).
                daemon=True,
            )
            thread.start()
            self._loop = loop
            log.debug("LLM 전용 이벤트 루프를 기동했습니다 (thread=%s).", thread.name)
            return loop

    @staticmethod
    def _run_forever(loop: asyncio.AbstractEventLoop) -> None:
        asyncio.set_event_loop(loop)
        loop.run_forever()

    def run(self, coro: Any, *, timeout: float) -> Any:
        """코루틴을 영속 루프에서 실행하고 결과를 동기적으로 기다린다."""
        future = asyncio.run_coroutine_threadsafe(coro, self._ensure())
        try:
            return future.result(timeout)
        except FutureTimeoutError:
            # 취소하지 않으면 루프에 매달린 채로 계속 토큰을 태운다.
            future.cancel()
            raise TimeoutError(
                f"LLM 호출이 {timeout:.0f}초 안에 끝나지 않아 취소했습니다."
            ) from None


_LOOP = _PersistentLoop()


def structured_output(agent: Any, output_model: type[T], prompt: str) -> T:
    """`agent.structured_output(output_model, prompt)`의 안전한 대체품.

    **에이전트 코드는 `agent.structured_output(...)`을 직접 부르지 말고 반드시
    이 함수를 쓴다.** 직접 부르면 위 docstring의 `Event loop is closed`가
    두 번째 요청부터 재발한다.

    Args:
        agent: strands `Agent` (테스트에서는 `MagicMock`).
        output_model: 구조화 출력으로 받을 Pydantic 모델.
        prompt: 이번 호출에만 쓰는 프롬프트 (대화 이력에 추가되지 않는다).

    Returns:
        `output_model` 인스턴스.
    """
    result = agent.structured_output_async(output_model, prompt)

    # 테스트가 꽂는 `MagicMock`은 awaitable이 아닌 값을 그대로 돌려준다.
    # 그 경우 루프를 띄울 이유가 없다 (mock 때문에 스레드를 만들지 않는다).
    if not inspect.isawaitable(result):
        return result  # type: ignore[return-value]

    return _LOOP.run(result, timeout=_call_timeout())
