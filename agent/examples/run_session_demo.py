"""전체 파이프라인 실행 예시.

실제 LLM 호출이 일어나므로 .env에 모델 프로바이더/API 키가 설정되어 있어야 합니다.

    cd agent
    cp .env.example .env   # 값 채우기
    python -m examples.run_session_demo

개입 파이프라인 3종(struggle / skip / paste)을 돌리고, 개입이 일어난 경우에는
학생이 답을 보낸 상황까지 이어서 보여줍니다 (응답 파이프라인).

출력에서 눈으로 확인할 것: **"학생에게 보이는 문구"에 3인칭 분석문이나 내부
어휘(지도 방식, hint_level 등)가 섞여 있지 않아야 합니다.** 내부 판단은 그
아래 "내부 판단" 항목에만 있어야 합니다.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from tutor_agent.orchestrator import TutorPipeline  # noqa: E402
from tutor_agent.schemas import SessionContext, StudentReply  # noqa: E402


def _print_result(label: str, result) -> None:
    print(f"\n=== {label} ===")
    print("\n[학생에게 보이는 문구]")
    if result.tutor_message is None:
        print("  (없음 — 개입하지 않거나 아무 말도 하지 않기로 함)")
    else:
        print(f"  {result.tutor_message.message}")
        if result.tutor_message.expects_reply:
            print(f"  → 학생의 답을 기다리는 질문: {result.tutor_message.question}")

    print("\n[내부 판단 — 학생에게 보이지 않음]")
    print(f"  학생 상태: {result.student_state}")
    print(f"  지도 계획: {result.guidance_plan}")
    print(f"  행동 계획: {result.action_plan}")


def _print_reply(reply_result, answer: str) -> None:
    print(f"\n  --- 학생이 답했다: {answer!r} ---")
    print("\n  [학생 답변 평가 — 내부용]")
    e = reply_result.evaluation
    print(f"    이해도: {e.understanding} / 정답 여부: {e.is_correct}")
    print(f"    오개념: {e.misconceptions}")
    print(f"    다음 초점: {e.next_focus}")
    print("\n  [튜터의 답장 — 학생에게 보이는 문구]")
    print(f"    {reply_result.tutor_message.message}")


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
    struggle_result = pipeline.run(struggle_ctx)
    _print_result("막힘 신호 2개 이상 (struggle)", struggle_result)

    # 학생이 그 개입에 답을 보냈다면 → 응답 파이프라인 (답변 평가 → 이어지는 말).
    if struggle_result.tutor_message is not None:
        answer = "잘 모르겠어요. 짝수인지 어떻게 확인하죠?"
        _print_reply(
            pipeline.respond_to_student(
                struggle_ctx,
                StudentReply(answer=answer, question=struggle_result.tutor_message.question),
            ),
            answer,
        )

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
    paste_result = pipeline.run(paste_ctx)
    _print_result("붙여넣기 감지 (comprehension check)", paste_result)

    # 이해도 확인 분기가 학생 답변 평가 루프를 쓰는 대표 경로다: 튜터가 "왜 이렇게
    # 동작하는지 설명해볼래요?"라고 묻고, 학생 설명을 평가해 실제로 이해했는지 본다.
    if paste_result.tutor_message is not None:
        answer = "리스트에서 2로 나눈 나머지가 0인 것만 골라서 다 더한 거예요."
        _print_reply(
            pipeline.respond_to_student(
                paste_ctx,
                StudentReply(answer=answer, question=paste_result.tutor_message.question),
            ),
            answer,
        )


if __name__ == "__main__":
    main()
