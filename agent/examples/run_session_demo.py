"""전체 파이프라인 실행 예시.

실제 LLM 호출이 일어나므로 .env에 모델 프로바이더/API 키가 설정되어 있어야 합니다.

    cd agent
    cp .env.example .env   # 값 채우기
    python -m examples.run_session_demo
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from tutor_agent.orchestrator import TutorPipeline  # noqa: E402
from tutor_agent.schemas import SessionContext  # noqa: E402


def _print_result(label: str, result) -> None:
    print(f"\n=== {label} ===")
    print("학생 상태 (entry_branch로 규칙 게이트 경로 확인 가능):", result.student_state)
    print("지도 방법:", result.guidance_plan)
    print("행동 계획:", result.action_plan)
    print("평가:", result.evaluation)


def main() -> None:
    pipeline = TutorPipeline()

    # 시나리오 1: 막힘 신호 2개(유휴 + 연속 실패)가 겹쳐 state_agent의 규칙 게이트를
    # 통과 → LLM 평가부터 파이프라인이 이어진다 (entry_branch="struggle").
    struggle_ctx = SessionContext(
        student_id="stu_001",
        problem_id="sum_even",
        code="def sum_even(numbers):\n    pass\n",
        run_history=["0/5 tests passed", "0/5 tests passed"],
        elapsed_seconds=240,
        idle_seconds=90,
        last_error="AssertionError: expected 6, got None",
        cursor_stuck_seconds=100,
        edit_churn_count=1,
        seconds_since_last_intervention=None,
    )
    _print_result("막힘 신호 2개 이상 (struggle)", pipeline.run(struggle_ctx))

    # 시나리오 2: 신호가 1개뿐이면 게이트에서 스킵 → LLM 호출 없이 종료 (entry_branch="skip").
    idle_only_ctx = SessionContext(
        student_id="stu_002",
        problem_id="sum_even",
        code="def sum_even(numbers):\n    return [n for n in numbers if n % 2 == 0]\n",
        idle_seconds=70,
    )
    _print_result("신호 1개뿐 (skip)", pipeline.run(idle_only_ctx))

    # 시나리오 3: 붙여넣기 감지 → LLM 평가를 건너뛰고 바로 "이해도 확인" 분기 (entry_branch="paste").
    paste_ctx = SessionContext(
        student_id="stu_003",
        problem_id="sum_even",
        code="def sum_even(numbers):\n    return sum(n for n in numbers if n % 2 == 0)\n",
        paste_detected=True,
    )
    _print_result("붙여넣기 감지 (comprehension check)", pipeline.run(paste_ctx))


if __name__ == "__main__":
    main()
