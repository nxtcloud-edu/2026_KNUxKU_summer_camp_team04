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


def main() -> None:
    ctx = SessionContext(
        student_id="stu_001",
        problem_id="sum_even",
        code="def sum_even(numbers):\n    pass\n",
        run_history=["0/5 tests passed", "0/5 tests passed"],
        elapsed_seconds=240,
        idle_seconds=90,
        last_error="AssertionError: expected 6, got None",
    )

    pipeline = TutorPipeline()
    result = pipeline.run(ctx)

    print("진입 결정:", result.entry_decision)
    print("학생 상태:", result.student_state)
    print("지도 방법:", result.guidance_plan)
    print("행동 계획:", result.action_plan)
    print("평가:", result.evaluation)


if __name__ == "__main__":
    main()
