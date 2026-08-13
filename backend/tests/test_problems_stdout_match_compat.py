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

from app.problems.schemas import ProblemDetail
from app.problems.service import ProblemRepository, parse_problem

JUDGE_PROBLEMS_DIR = Path(__file__).resolve().parents[2] / "judge" / "problems"


def test_stdout_match_problem_parses_without_function_name():
    data = json.loads(
        (JUDGE_PROBLEMS_DIR / "stdout_bigger_number.json").read_text(encoding="utf-8")
    )
    record = parse_problem(data)

    assert record.problem_id == "stdout_bigger_number"
    assert record.check_type == "stdout_match"
    assert record.function_name is None  # stdin/stdout 채점이라 필요 없는 필드
    assert len(record.public_test_cases) == 2
    assert len(record.hidden_test_cases) == 6

    # **원본 키를 그대로 보존한다.** input/expected로 뭉개면 프론트의
    # formatPublicTest가 `stdin !== undefined` 분기를 놓쳐 예제가 잘못 렌더된다.
    tc = record.public_test_cases[0]
    assert tc.stdin == "10 -3\n"
    assert tc.expected_stdout == "0\n"
    assert tc.input is None
    assert tc.expected is None
    assert tc.category == "sample_1"


def test_stdout_match_detail_response_keeps_original_keys():
    """API 응답 스키마에서도 stdin/expected_stdout이 살아 있어야 한다.

    프론트(App.tsx의 formatPublicTest)가 `test.stdin !== undefined`로 렌더링을
    분기하므로, 여기서 뭉개지면 stdout 문제의 예제가
    `입력 ["10 -3\\n"] → 결과 "0\\n"`처럼 잘못 표시된다.
    """
    repo = ProblemRepository(JUDGE_PROBLEMS_DIR)
    detail = ProblemDetail.from_record(repo.get("stdout_bigger_number"))

    tc = detail.public_test_cases[0]
    assert tc.stdin == "10 -3\n"
    assert tc.expected_stdout == "0\n"
    assert tc.input is None

    # 단수 concept 키 + 제한값이 응답에 실린다
    dumped = detail.model_dump()
    assert "concept" in dumped and "concepts" not in dumped
    assert dumped["time_limit_sec"] == 1.0
    assert dumped["memory_limit_mb"] == 128
    assert dumped["function_name"] is None


def test_repository_skips_broken_file_instead_of_dying(tmp_path):
    """파일 하나가 깨져도 저장소 전체가 죽으면 안 된다.

    예전에는 예외가 __init__을 뚫고 나가 get_problem_repository()의 의존성 주입이
    실패했고, /problems뿐 아니라 /sessions와 /run까지 전부 500이 됐다.
    """
    (tmp_path / "good.json").write_text(
        json.dumps(
            {
                "problem_id": "good",
                "title": "정상",
                "check_type": "function_call",
                "function_name": "f",
                "code_template": "def f(): pass",
                "public_test_cases": [{"input": [1], "expected": 1}],
                "hidden_test_cases": [],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "broken.json").write_text("{ not json", encoding="utf-8")

    repo = ProblemRepository(tmp_path)

    assert [r.problem_id for r in repo.list()] == ["good"]
    assert repo.exists("good")
    assert not repo.exists("broken")


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
