"""문제 저장소.

문제는 DB가 아니라 app/problems/data/*.json이 진실이다 (models.py 상단 주석 참조).
파일을 시작 시 한 번 읽어 메모리에 들고 있는다. 문제 3개, 런타임 쓰기 없음.

여기서 파싱한 ProblemRecord는 **라우터 경계를 넘지 않는다.**
hidden test case는 이 dataclass 안에만 존재하고, 응답 스키마(ProblemDetail)에는
그걸 담을 수 있는 필드가 아예 없다. 유출 방지가 절차가 아니라 구조인 이유다.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.errors import ProblemNotFound


@dataclass(frozen=True)
class TestCase:
    input: list[Any]
    expected: Any
    category: str = "basic"


@dataclass(frozen=True)
class ProblemRecord:
    problem_id: str
    title: str
    description: str
    difficulty: str
    concepts: list[str]
    check_type: str
    function_name: str
    code_template: str
    public_test_cases: list[TestCase] = field(default_factory=list)
    hidden_test_cases: list[TestCase] = field(default_factory=list)

    @property
    def hidden_test_categories(self) -> list[str]:
        """중복 제거된 hidden 카테고리. 입력값이 아니라 카테고리만 나가므로 공개 안전하다."""
        seen: list[str] = []
        for tc in self.hidden_test_cases:
            if tc.category not in seen:
                seen.append(tc.category)
        return seen


def _parse_test_cases(raw: Any) -> list[TestCase]:
    out: list[TestCase] = []
    for tc in raw or []:
        out.append(
            TestCase(
                input=tc["input"],
                expected=tc["expected"],
                category=tc.get("category", "basic"),
            )
        )
    return out


def parse_problem(data: dict[str, Any]) -> ProblemRecord:
    """문제 JSON 하나를 파싱한다.

    키 이름은 origin/judge의 파일 기준을 채택했다 (problem_id, code_template) --
    병합 시 rename이 0이 된다. backend_plan §5의 id/starter_code/concepts도 입력으로 받아준다.
    description/difficulty는 judge 파일에 없으므로 부재를 허용한다.

    **주의: judge/problems 26개 중 3개만 파싱된다.** stdout_match 문제 23개는
    function_name 키가 없어(stdin/stdout으로 채점하므로 불필요) KeyError가 나고,
    그걸 고쳐도 테스트케이스 키가 {stdin, expected_stdout}이라 다시 깨진다.
    PROBLEMS_DIR을 judge 쪽으로 돌리려면 stdout_match 지원을 먼저 넣어야 한다.
    """
    concepts = data.get("concepts") or data.get("concept") or []
    return ProblemRecord(
        problem_id=data.get("problem_id") or data["id"],
        title=data["title"],
        description=data.get("description", ""),
        difficulty=data.get("difficulty", "BEGINNER"),
        concepts=list(concepts),
        check_type=data.get("check_type", "function_call"),
        function_name=data["function_name"],
        code_template=data.get("code_template") or data.get("starter_code", ""),
        public_test_cases=_parse_test_cases(data.get("public_test_cases")),
        hidden_test_cases=_parse_test_cases(data.get("hidden_test_cases")),
    )


class ProblemRepository:
    def __init__(self, directory: Path) -> None:
        self._dir = directory
        self._by_id: dict[str, ProblemRecord] = {}
        self._order: list[str] = []
        self.reload()

    def reload(self) -> None:
        self._by_id.clear()
        self._order.clear()
        if not self._dir.exists():
            return
        for path in sorted(self._dir.glob("*.json")):
            record = parse_problem(json.loads(path.read_text(encoding="utf-8")))
            self._by_id[record.problem_id] = record
            self._order.append(record.problem_id)

    def list(self) -> list[ProblemRecord]:
        return [self._by_id[pid] for pid in self._order]

    def get(self, problem_id: str) -> ProblemRecord:
        try:
            return self._by_id[problem_id]
        except KeyError:
            raise ProblemNotFound(problem_id) from None

    def exists(self, problem_id: str) -> bool:
        return problem_id in self._by_id


@lru_cache
def get_problem_repository() -> ProblemRepository:
    return ProblemRepository(get_settings().problems_path)
