"""judge 샌드박스 어댑터 (`judge_service.run_judge_for_problem()`).

셋업 체크리스트 (압박 상황에서 재발견하지 않도록 README에도 있다):
  1. `pip install "docker>=7.0"`; judge/ 에서 `docker build -t judge-sandbox .`
  2. .env: JUDGE_BACKEND=docker, JUDGE_PATH=../judge
  3. 문제 디렉터리는 backend의 PROBLEMS_DIR + GENERATED_PROBLEMS_DIR **뿐이다.**
     judge/problems를 judge가 직접 읽지 않으므로(아래 to_judge_problem 참고)
     양쪽 problem_id 집합이 어긋날 걱정이 없다.
  4. judge는 runtime_ms를 반환하지 않는다 -> null로 남는다.
  5. judge는 mode="submit" + WRONG_ANSWER일 때만 failed_categories를 준다.
     아래 .get(..., [])가 이미 그걸 허용한다.
"""
from __future__ import annotations

import sys
from dataclasses import asdict
from typing import Any

from app.config import get_settings
from app.enums import JudgeStatus
from app.judge.interface import JudgeMode, JudgeResult
from app.problems.service import ProblemRecord, TestCase


def _case_payload(tc: TestCase) -> dict[str, Any]:
    """`TestCase` -> judge 하네스가 읽는 dict. **None인 키는 빼고 보낸다.**

    check_type별로 채워지는 필드가 다르므로(function_call은 input/expected,
    stdout_match는 stdin/expected_stdout) 반대쪽 필드는 None으로 남아 있다.
    그걸 그대로 실으면 problems/*.json 원본에 없던 키가 생겨 하네스가 보는
    모양이 파일과 달라진다.
    """
    return {k: v for k, v in asdict(tc).items() if v is not None}


def to_judge_problem(problem: ProblemRecord) -> dict[str, Any]:
    """`ProblemRecord` -> judge `run_judge_for_problem()`이 받는 문제 dict.

    **왜 problem_id를 넘기지 않는가.** judge의 `run_judge(code, problem_id)`는
    `judge/problems/{problem_id}.json`을 자기가 읽는다. 그러면 backend가 아는
    문제와 judge가 채점할 수 있는 문제가 갈린다 — 실제로 복습 문제
    (`backend/generated_problems/`에 저장된다)를 제출하면 judge가 파일을 못 찾아
    `ProblemNotFoundError`로 500이 났다. **문제의 진실은 backend의
    `ProblemRepository` 하나**이고 judge는 넘겨받은 문제를 채점하는 실행기여야
    한다. 그래서 dict를 직접 넘기는 `run_judge_for_problem()`을 쓴다(judge가
    문제 생성 검증용으로 이미 열어둔 seam이다). 부수효과로 이 파일 상단
    체크리스트 3번의 "디렉터리 둘이 drift" 위험도 사라진다.

    `time_limit_sec`/`memory_limit_mb`는 **없을 때 키 자체를 넣지 않는다.**
    judge가 `problem.get("time_limit_sec", DEFAULT)`로 읽으므로 None을 실으면
    기본값 대신 None이 들어가 계산이 깨진다 (judge 문제 3개가 이 값이 없다).
    """
    payload: dict[str, Any] = {
        "check_type": problem.check_type,
        "public_test_cases": [_case_payload(tc) for tc in problem.public_test_cases],
        "hidden_test_cases": [_case_payload(tc) for tc in problem.hidden_test_cases],
    }
    if problem.check_type == "function_call":
        payload["function_name"] = problem.function_name
    if problem.time_limit_sec is not None:
        payload["time_limit_sec"] = problem.time_limit_sec
    if problem.memory_limit_mb is not None:
        payload["memory_limit_mb"] = problem.memory_limit_mb
    return payload


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
        from judge_service import (  # type: ignore[import-not-found]
            run_judge_for_problem,
        )

        raw = run_judge_for_problem(code, to_judge_problem(problem), mode)
        return JudgeResult(
            status=JudgeStatus(raw["status"]),
            passed=raw["passed"],
            total=raw["total"],
            runtime_ms=raw.get("runtime_ms"),
            message=raw.get("message"),
            failed_categories=raw.get("failed_categories", []),
        )
