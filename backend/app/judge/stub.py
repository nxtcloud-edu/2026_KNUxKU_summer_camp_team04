from __future__ import annotations

from app.enums import JudgeStatus
from app.errors import JudgeUnavailable
from app.judge.interface import JudgeMode, JudgeResult
from app.problems.service import ProblemRecord


class UnavailableJudge:
    """오늘 기본값. 서버 사이드 실행이 아직 없다."""

    name = "unavailable"

    def is_available(self) -> bool:
        return False

    def judge(
        self, *, code: str, problem: ProblemRecord, mode: JudgeMode
    ) -> JudgeResult:
        raise JudgeUnavailable(
            "서버 사이드 Judge가 아직 구성되지 않았습니다. "
            "오늘은 브라우저에서 채점하고 POST /sessions/{id}/results 로 결과를 보내세요. "
            "(JUDGE_BACKEND=docker 로 서버 채점을 활성화할 수 있습니다.)"
        )


class FakeJudge:
    """테스트 전용. 미리 정한 결과를 순서대로 돌려준다."""

    name = "fake"

    def __init__(self, results: list[JudgeResult] | None = None) -> None:
        self._queue = list(results or [])

    def is_available(self) -> bool:
        return True

    def judge(
        self, *, code: str, problem: ProblemRecord, mode: JudgeMode
    ) -> JudgeResult:
        if self._queue:
            return self._queue.pop(0)
        return JudgeResult(status=JudgeStatus.WRONG_ANSWER, passed=0, total=1)
