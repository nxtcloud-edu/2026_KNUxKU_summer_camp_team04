"""judge_service.capture_reference_outputs()의 어댑터.

problem_generator_agent가 LLM으로 만든 문제 템플릿(ProblemTemplate)을 judge
샌드박스에서 실제로 실행해 검증한다. backend의 `app/judge/docker_judge.py`와
같은 seam 패턴(JUDGE_PATH를 sys.path에 넣고 judge_service를 직접 import)을
그대로 따른다 — HTTP 왕복 없이 붙는다.

핵심 원칙: LLM이 주장하는 expected/expected_stdout은 절대 그대로 쓰지 않는다.
reference_solution을 judge 샌드박스에서 실제로 실행해 나온 출력을 "진짜
expected"로 채택한다 (judge/CLAUDE.md의 capture_reference_outputs 참고).
"""

from __future__ import annotations

import os
import sys

from ..schemas import ProblemTemplate, ValidationReport


def _judge_path() -> str:
    return os.getenv("JUDGE_PATH", "../judge")


def _import_judge_service():
    """judge_service 모듈을 sys.path에 JUDGE_PATH를 넣어 직접 import한다.

    지연 import로 둔다 — judge_service는 docker SDK가 필수라, 이 모듈을
    import하는 시점에 docker가 필수 의존성이 되지 않게 하기 위함
    (backend의 DockerJudge.is_available()과 같은 이유).
    """
    path = _judge_path()
    if path not in sys.path:
        sys.path.insert(0, path)
    import judge_service  # type: ignore[import-not-found]

    return judge_service


def validate_template(template: ProblemTemplate) -> ValidationReport:
    """레퍼런스 정답 코드를 judge 샌드박스에서 실행해 template을 검증한다.

    1. capture_reference_outputs()로 reference_solution을 test_case_inputs에
       대해 실제 실행 -> 나온 출력을 expected/expected_stdout으로 채택.
       SYNTAX_ERROR/TIME_LIMIT/RUNTIME_ERROR면 즉시 반려.
    2. 캡처 도중 일부 케이스만 개별 오류를 내면(예: 특정 입력에서만 예외)
       그 카테고리를 failed_categories에 기록하고 반려 — 레퍼런스 코드가
       자기가 낸 입력값 중 일부를 처리 못 한다는 뜻이라 문제 자체가 이상함.
    3. 통과하면 problems/*.json과 동일한 스키마의 dict를 만들어 반환한다
       (problem_id는 저장 시점에 호출자가 부여 — 여기서는 붙이지 않음).
    """
    categories = [tc.category for tc in template.test_case_inputs]
    duplicates = {c for c in categories if categories.count(c) > 1}
    if duplicates:
        return ValidationReport(
            is_valid=False,
            error_message=f"test_case_inputs에 category가 중복됩니다: {sorted(duplicates)}. category는 서로 달라야 합니다.",
        )

    judge_service = _import_judge_service()

    capture = judge_service.capture_reference_outputs(
        reference_code=template.reference_solution,
        check_type=template.check_type,
        function_name=template.function_name,
        test_case_inputs=[tc.model_dump(exclude_none=True) for tc in template.test_case_inputs],
        time_limit_sec=template.time_limit_sec or judge_service.DEFAULT_TIME_LIMIT_SEC,
        memory_limit_mb=template.memory_limit_mb or judge_service.DEFAULT_MEM_LIMIT_MB,
    )

    if capture["status"] != "OK":
        return ValidationReport(
            is_valid=False,
            error_message=f"레퍼런스 코드 실행 실패 ({capture['status']}): {capture.get('message', '')}",
        )

    failed_categories = [output["category"] for output in capture["outputs"] if "error" in output]
    if failed_categories:
        return ValidationReport(
            is_valid=False,
            error_message="레퍼런스 코드가 일부 입력값에서 오류를 냈습니다 — 문제나 레퍼런스 코드를 다시 확인하세요.",
            failed_categories=failed_categories,
        )

    problem_json = _build_problem_json(template, capture["outputs"])
    return ValidationReport(is_valid=True, problem_json=problem_json)


def _build_problem_json(template: ProblemTemplate, outputs: list[dict]) -> dict:
    """검증된 실제 출력을 problems/*.json 스키마(public/hidden 분리)로 합친다.

    outputs는 judge_service.capture_reference_outputs()가 test_case_inputs와
    항상 같은 순서로 반환하므로 인덱스로 페어링한다 — category로 dict를 만들어
    매칭하면 category가 중복될 때 서로 다른 케이스의 출력이 뒤섞이는 버그가
    생긴다 (validate_template()에서 사전에 걸러내지만, 그 체크에만 의존하지
    않도록 여기서도 안전하게 위치 기반으로 짠다).
    """
    public_cases: list[dict] = []
    hidden_cases: list[dict] = []
    for tc, output in zip(template.test_case_inputs, outputs, strict=True):
        actual_output = output["output"]
        if template.check_type == "stdout_match":
            case = {"stdin": tc.stdin, "expected_stdout": actual_output, "category": tc.category}
        else:
            case = {"input": tc.input, "expected": actual_output, "category": tc.category}
        (hidden_cases if tc.is_hidden else public_cases).append(case)

    problem: dict = {
        "title": template.title,
        "description": template.description,
        "concept": template.concept,
        "check_type": template.check_type,
        "code_template": template.code_template,
        "public_test_cases": public_cases,
        "hidden_test_cases": hidden_cases,
    }
    if template.check_type == "function_call":
        problem["function_name"] = template.function_name
    if template.time_limit_sec is not None:
        problem["time_limit_sec"] = template.time_limit_sec
    if template.memory_limit_mb is not None:
        problem["memory_limit_mb"] = template.memory_limit_mb
    return problem
