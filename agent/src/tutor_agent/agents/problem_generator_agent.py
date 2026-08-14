"""오답/복습 기반 새 문제 생성 에이전트.

기존 튜터 파이프라인(entry -> state -> guidance -> action -> evaluation)과는
별개의 기능이다. 학생이 특정 개념에서 반복적으로 오답을 내면 그 개념을 다시
연습할 문제를 새로 만든다.

LLM 호출을 복습 횟수에 비례해서 늘리지 않기 위해, 실제 생성 요청은 4계층
정책(문제 뱅크 검색 -> 코스메틱 변주 -> 인스턴스 랜덤화 -> 새 템플릿 생성) 중
가장 드문 마지막 계층에서만 이 에이전트를 호출한다고 가정한다 (그 앞 3계층은
LLM을 안 쓰는 순수 코드 로직이라 이 파일의 책임이 아님).

LLM이 만든 문제/레퍼런스 코드가 틀릴 수 있으므로, judge 샌드박스
(tools/judge_validator.py)로 검증을 통과한 결과만 반환한다. 검증에 실패하면
실패 이유를 다음 프롬프트에 피드백으로 넣어 재시도하되, 토큰 낭비를 막기
위해 재시도 횟수를 MAX_RETRIES로 캡핑한다.
"""

from __future__ import annotations

from strands import Agent

from ..models import get_model
from ..schemas import ProblemTemplate, ReviewRequest, ValidationReport
from ..tools.judge_validator import validate_template

ROLE = "problem_generator"

#: judge 검증 실패 시 재시도할 최대 횟수 (최초 시도 제외). 무한 재시도로
#: 토큰이 새는 것을 막는 캡 — 여기까지 실패하면 사람 리뷰로 넘기는 게 맞다.
MAX_RETRIES = 2

SYSTEM_PROMPT = """\
당신은 코딩 학습 튜터 시스템의 '복습 문제 생성 에이전트'입니다.
학생이 특정 개념에서 반복적으로 틀렸다는 정보를 받아, 그 개념을 다시
연습할 수 있는 새 문제를 하나 만드세요.

반드시 지킬 것:
1. reference_solution은 실제로 문제를 정확히 푸는 코드여야 합니다. 여기서
   당신이 틀리면 judge가 자동으로 거부하고 이유를 알려줍니다 — 그 이유를
   보고 다음 시도에서 고치세요.
2. expected 값은 계산해서 넣지 마세요. test_case_inputs에는 입력값(stdin
   또는 input)만 넣고, 출력은 judge가 reference_solution을 실제로 실행해서
   확정합니다.
3. 학생이 이전에 틀렸던 문제와 완전히 동일한 문제를 그대로 복제하지 말고,
   같은 개념을 다른 맥락/각도로 연습하게 하세요.
4. public/hidden 테스트케이스를 골고루 섞고, 경계값(0, 음수, 최댓값 등)을
   최소 하나는 hidden으로 포함하세요.
5. test_case_inputs는 4~8개면 충분합니다. 절대 문자열이 아니라 JSON 배열이어야
   하고, `range(...)`나 리스트 컴프리헨션 같은 파이썬 표현식을 쓰면 안 됩니다 —
   각 원소를 실제 값으로 하나씩 직접 쓰세요.
"""


def build_agent() -> Agent:
    return Agent(
        name="problem_generator_agent",
        model=get_model(ROLE),
        system_prompt=SYSTEM_PROMPT,
    )


def generate(request: ReviewRequest, agent: Agent | None = None) -> ValidationReport:
    """judge 검증을 통과할 때까지 (최초 시도 + 최대 MAX_RETRIES회) 문제 생성을 시도한다.

    마지막 시도까지 실패하면 그 실패 상태의 ValidationReport를 그대로
    반환한다 (호출자가 사람 리뷰 큐로 넘기거나 상위 정책에 알리는 걸 결정).
    """
    agent = agent or build_agent()
    prompt = f"다음 복습 요청에 맞는 문제를 하나 만드세요:\n\n{request.model_dump_json(indent=2)}"

    report: ValidationReport | None = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            template: ProblemTemplate = agent.structured_output(ProblemTemplate, prompt)
        except Exception as exc:
            # 실제로 관찰된 실패 모드: LLM이 test_case_inputs를 리스트가 아니라
            # (파이썬 range() 표현식이 섞인) 문자열로 반환해 Pydantic 검증 자체가
            # 여기서 터짐. judge 검증 실패와 동일하게 재시도 피드백으로 돌린다 —
            # 이걸 안 잡으면 generate()가 그냥 예외로 죽어서 재시도 루프가 무의미해짐.
            report = ValidationReport(
                is_valid=False,
                error_message=f"LLM 응답이 ProblemTemplate 스키마에 맞지 않습니다: {exc}",
            )
        else:
            report = validate_template(template)

        if report.is_valid:
            return report

        prompt = (
            f"방금 만든 문제가 검증에서 실패했습니다 (시도 {attempt + 1}/{MAX_RETRIES + 1}).\n"
            f"실패 이유: {report.error_message}\n"
            f"실패한 테스트케이스: {report.failed_categories}\n\n"
            "위 이유를 참고해서 reference_solution과 문제를 다시 만드세요. "
            "test_case_inputs는 반드시 JSON 배열이어야 하며, 문자열로 감싸거나 "
            "range()처럼 파이썬 표현식을 쓰면 안 됩니다.\n\n"
            f"원래 요청:\n{request.model_dump_json(indent=2)}"
        )

    return report
