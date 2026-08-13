"""origin/judge의 run_judge() 어댑터.

오늘은 실행되지 않지만 **지금** 작성해둔다. 병합 시 JUDGE_BACKEND=docker만 바꾸면
프론트/백엔드 어느 쪽도 코드 수정 없이 켜진다. 그게 seam이다.

병합 체크리스트 (압박 상황에서 재발견하지 않도록 README에도 있다):
  1. `pip install "docker>=7.0"`; judge/ 에서 `docker build -t judge-sandbox .`
  2. .env: JUDGE_BACKEND=docker, JUDGE_PATH=../judge
  3. 문제 디렉터리를 **하나로 정한다.** PROBLEMS_DIR을 judge/problems로 돌리거나
     (우리 JSON의 description/difficulty 키를 그쪽에 복사), 우리 것을 유지하되
     양쪽 problem_id 집합이 같은지 확인. 디렉터리 둘이 drift 위험이다.
  4. run_judge()는 runtime_ms를 반환하지 않는다 -> BE1이 한 줄 추가하거나 null로 남는다.
  5. run_judge()는 mode="submit" + WRONG_ANSWER일 때만 failed_categories를 준다.
     아래 .get(..., [])가 이미 그걸 허용한다.
"""
from __future__ import annotations

import sys

from app.config import get_settings
from app.enums import JudgeStatus
from app.judge.interface import JudgeMode, JudgeResult
from app.problems.service import ProblemRecord


class DockerJudge:
    name = "docker"

    def is_available(self) -> bool:
        try:
            import docker  # 지연 import: docker SDK를 필수 의존성으로 만들지 않는다

            docker.from_env().ping()
            return True
        except Exception:
            return False

    def judge(
        self, *, code: str, problem: ProblemRecord, mode: JudgeMode
    ) -> JudgeResult:
        s = get_settings()
        if s.judge_path and s.judge_path not in sys.path:
            sys.path.insert(0, s.judge_path)
        from judge_service import run_judge  # type: ignore[import-not-found]

        raw = run_judge(code, problem.problem_id, mode=mode)
        return JudgeResult(
            status=JudgeStatus(raw["status"]),
            passed=raw["passed"],
            total=raw["total"],
            runtime_ms=raw.get("runtime_ms"),
            message=raw.get("message"),
            failed_categories=raw.get("failed_categories", []),
        )
