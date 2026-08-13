"""Judge seam.

BE1의 Docker judge가 나중에 이 자리에 그대로 꽂힌다. app/trace/* 는 절대 건드리지 않는다.

두 가지 의도적 선택:

**동기다, async가 아니다.** BE1의 judge는 blocking Docker I/O(`container.wait`)다.
FastAPI는 이미 def 핸들러를 threadpool에서 돌리므로 동기 프로토콜이 옳고 더 단순하다.
async 코드에서 불러야 하면 `await run_in_threadpool(judge.judge, ...)`.
프로토콜을 async로 선언하면 BE1이 blocking 호출을 감싸거나, 더 나쁘게는 event loop를 막는다.

**judge()는 problem_id가 아니라 로드된 ProblemRecord를 받는다.** 의존 방향이 뒤집힌다:
judge가 파일시스템을 만지지 않으므로 시스템에 문제 로더가 정확히 하나만 존재하고,
judge는 리터럴 객체 하나로 파일 없이 테스트 가능해진다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol, runtime_checkable

from app.enums import JudgeStatus
from app.problems.service import ProblemRecord

JudgeMode = Literal["run", "submit"]


@dataclass(frozen=True)
class JudgeResult:
    status: JudgeStatus
    passed: int
    total: int
    runtime_ms: int | None = None
    message: str | None = None
    failed_categories: list[str] = field(default_factory=list)


@runtime_checkable
class JudgeProtocol(Protocol):
    name: str

    def is_available(self) -> bool: ...

    def judge(
        self, *, code: str, problem: ProblemRecord, mode: JudgeMode
    ) -> JudgeResult: ...
