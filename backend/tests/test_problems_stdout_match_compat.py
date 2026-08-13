"""judge/problems의 stdout_match 문제가 parse_problem()에서 크래시 없이
파싱되는지 확인하는 회귀 테스트.

배경: judge/problems 26개 중 3개(function_call)만 이 파서로 읽혔고, 23개
(stdout_match)는 function_name 키가 없어 KeyError가 났었다 (service.py의
parse_problem 참고). PROBLEMS_DIR을 judge 쪽으로 통합하기 전에, 최소한
파싱만은 전부 되는지 이 테스트로 보장한다.

app/problems/data/*.json(지금 진짜 PROBLEMS_DIR)이 아니라 judge/problems를
직접 읽는다 -- PROBLEMS_DIR 전환 여부와 무관하게 파서 자체의 호환성만 검증.
"""
from __future__ import annotations

import json
from pathlib import Path

from app.problems.service import parse_problem

JUDGE_PROBLEMS_DIR = Path(__file__).resolve().parents[2] / "judge" / "problems"


def test_stdout_match_problem_parses_without_function_name():
    data = json.loads(
        (JUDGE_PROBLEMS_DIR / "stdout_bigger_number.json").read_text(encoding="utf-8")
    )
    record = parse_problem(data)

    assert record.problem_id == "stdout_bigger_number"
    assert record.check_type == "stdout_match"
    assert record.function_name == ""  # function_call과 달리 없어도 되는 필드
    assert len(record.public_test_cases) == 2
    assert len(record.hidden_test_cases) == 6

    tc = record.public_test_cases[0]
    assert tc.input == ["10 -3\n"]  # stdin은 [문자열] 하나로 감싼다
    assert tc.expected == "0\n"  # expected_stdout이 그대로 들어간다
    assert tc.category == "sample_1"


def test_all_judge_problems_parse_without_crashing():
    """judge/problems 26개(function_call 3개 + stdout_match 23개) 전부가
    KeyError 없이 파싱되는지 확인."""
    paths = list(JUDGE_PROBLEMS_DIR.glob("*.json"))
    assert len(paths) == 26, "judge/problems 문제 개수가 26개가 아니면 이 숫자도 갱신할 것"

    check_types_seen = set()
    for path in paths:
        data = json.loads(path.read_text(encoding="utf-8"))
        record = parse_problem(data)
        assert record.problem_id == path.stem
        check_types_seen.add(record.check_type)

    assert check_types_seen == {"function_call", "stdout_match"}


def test_function_call_parsing_still_works_as_before():
    """기존 function_call 문제(예: func_sum_list)가 이 수정으로 안 깨졌는지 확인."""
    data = json.loads(
        (JUDGE_PROBLEMS_DIR / "func_sum_list.json").read_text(encoding="utf-8")
    )
    record = parse_problem(data)

    assert record.check_type == "function_call"
    assert record.function_name == "sum_list"
    tc = record.public_test_cases[0]
    assert tc.input == [[1, 2, 3]]
    assert tc.expected == 6
