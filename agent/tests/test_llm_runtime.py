"""`llm_runtime` 테스트 — LLM 호출을 하나의 영속 이벤트 루프에서 돌리는 장치.

이 모듈이 왜 있는지는 `llm_runtime.py` docstring에 자세히 있다. 요약하면:
strands의 동기 `structured_output()`은 호출마다 새 이벤트 루프를 만들고 닫는데
(`asyncio.run` in a thread), 우리는 프로세스 내내 하나의 `Agent`(=하나의 httpx
연결 풀)를 재사용한다. 그 조합이 `RuntimeError: Event loop is closed`를 내거나
아예 멈춘다 (동시 요청 4개로 재현: 1라운드 통과 후 2라운드에서 무한 대기).

여기서는 실제 LLM 없이 배선만 검증한다: 코루틴이 정말로 **하나의** 루프에서
돌아가는가, 그 루프가 호출 사이에 닫히지 않는가, 동시 호출이 섞여도 되는가.
"""

from __future__ import annotations

import asyncio
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from tutor_agent import llm_runtime  # noqa: E402


class _Out:
    """구조화 출력 자리표시자 (Pydantic 모델일 필요가 없다)."""

    def __init__(self, value: object) -> None:
        self.value = value


def _async_agent(handler) -> MagicMock:
    """`structured_output_async`가 코루틴을 돌려주는 가짜 Agent."""
    agent = MagicMock()

    async def call(output_model, prompt):
        return await handler(output_model, prompt)

    agent.structured_output_async.side_effect = call
    return agent


# --- 기본 동작 ----------------------------------------------------------------


def test_awaits_the_coroutine_and_returns_its_value() -> None:
    async def handler(_model, prompt):
        return _Out(prompt)

    result = llm_runtime.structured_output(_async_agent(handler), _Out, "안녕")

    assert isinstance(result, _Out)
    assert result.value == "안녕"


def test_passes_the_output_model_and_prompt_through() -> None:
    agent = _async_agent(lambda model, prompt: _done(_Out(None)))

    llm_runtime.structured_output(agent, _Out, "프롬프트")

    assert agent.structured_output_async.call_args.args == (_Out, "프롬프트")


def _done(value):
    """이미 완료된 awaitable."""

    async def _inner():
        return value

    return _inner()


def test_non_awaitable_results_pass_straight_through() -> None:
    """테스트가 꽂는 MagicMock은 코루틴이 아니다 — 그 경우 루프를 띄우지 않는다."""
    agent = MagicMock()
    expected = _Out("mock")
    agent.structured_output_async.return_value = expected

    assert llm_runtime.structured_output(agent, _Out, "p") is expected


# --- 핵심: 루프가 하나뿐이고, 닫히지 않는다 ------------------------------------


def test_every_call_runs_on_the_same_never_closed_loop() -> None:
    """이게 이 모듈의 존재 이유다.

    호출마다 루프가 새로 생기면(=기존 strands 동작) 캐시된 httpx 풀이 닫힌 루프를
    참조하게 되어 `Event loop is closed`가 난다. 세 번 호출해서 세 번 모두 같은
    루프 객체였고, 호출이 끝난 뒤에도 그 루프가 살아 있는지 확인한다.
    """
    seen: list[asyncio.AbstractEventLoop] = []

    async def handler(_model, _prompt):
        seen.append(asyncio.get_running_loop())
        return _Out(None)

    agent = _async_agent(handler)
    for _ in range(3):
        llm_runtime.structured_output(agent, _Out, "p")

    assert len(seen) == 3
    assert len(set(id(loop) for loop in seen)) == 1, "호출마다 루프가 달라졌다"
    assert not seen[0].is_closed(), "호출이 끝난 뒤 루프가 닫혔다"


def test_the_loop_thread_is_a_daemon() -> None:
    """uvicorn 종료를 막지 않아야 한다 (Ctrl+C가 안 먹는 서버가 되면 안 된다)."""
    llm_runtime.structured_output(_async_agent(lambda m, p: _done(_Out(None))), _Out, "p")

    threads = [t for t in threading.enumerate() if t.name == "tutor-agent-llm-loop"]
    assert threads, "LLM 전용 루프 스레드를 찾지 못했다"
    assert all(t.daemon for t in threads)
    assert len(threads) == 1, "루프 스레드가 여러 개 생겼다"


def test_concurrent_calls_from_many_threads_all_succeed() -> None:
    """실제 사고 재현 조건: 여러 요청이 캐시된 Agent 하나를 동시에 쓴다.

    FastAPI는 sync 엔드포인트를 워커 스레드풀에서 돌리므로, `/decide` 두 건이
    겹치면 이 상황이 된다 (관찰된 로그에서 실제로 겹쳐 있었다).
    """
    async def handler(_model, prompt):
        await asyncio.sleep(0.01)  # 실제 LLM 대기를 흉내낸다
        return _Out(prompt)

    agent = _async_agent(handler)

    def one(i: int) -> object:
        return llm_runtime.structured_output(agent, _Out, f"p{i}").value

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(one, range(16)))

    assert sorted(results) == sorted(f"p{i}" for i in range(16))


# --- 타임아웃 -----------------------------------------------------------------


def test_a_hung_call_times_out_instead_of_wedging_forever(monkeypatch) -> None:
    """영속 루프에 영원히 매달린 코루틴이 쌓이면 안 된다 — 끊고 예외를 올린다.

    호출부(`backend_adapter`)가 그 예외를 받아 WAIT으로 폴백한다.
    """
    monkeypatch.setenv("LLM_CALL_TIMEOUT_SECONDS", "0.05")
    started = threading.Event()

    async def handler(_model, _prompt):
        started.set()
        await asyncio.sleep(30)
        return _Out(None)

    with pytest.raises(TimeoutError):
        llm_runtime.structured_output(_async_agent(handler), _Out, "p")

    assert started.is_set()  # 실제로 시작은 했다 (타임아웃이지 미호출이 아니다)


def test_a_bad_timeout_setting_falls_back_to_the_default(monkeypatch) -> None:
    """설정 오타 하나로 파이프라인이 죽는 것보다 기본값으로 도는 게 낫다."""
    monkeypatch.setenv("LLM_CALL_TIMEOUT_SECONDS", "아무말")

    assert llm_runtime._call_timeout() == llm_runtime.DEFAULT_CALL_TIMEOUT_SECONDS


def test_exceptions_from_the_coroutine_propagate() -> None:
    """LLM 오류를 조용히 먹으면 호출부가 폴백할 기회를 잃는다."""
    async def handler(_model, _prompt):
        raise ValueError("스키마 불일치")

    with pytest.raises(ValueError, match="스키마 불일치"):
        llm_runtime.structured_output(_async_agent(handler), _Out, "p")
