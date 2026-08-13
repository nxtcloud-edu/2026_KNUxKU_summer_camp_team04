"""문제 저장소.

문제는 DB가 아니라 app/problems/data/*.json이 진실이다 (models.py 상단 주석 참조).
파일을 시작 시 한 번 읽어 메모리에 들고 있는다. 문제 3개, 런타임 쓰기 없음.

여기서 파싱한 ProblemRecord는 **라우터 경계를 넘지 않는다.**
hidden test case는 이 dataclass 안에만 존재하고, 응답 스키마(ProblemDetail)에는
그걸 담을 수 있는 필드가 아예 없다. 유출 방지가 절차가 아니라 구조인 이유다.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.errors import ProblemNotFound

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class TestCase:
    """check_type에 따라 채워지는 필드가 다르다.

    function_call -> input / expected
    stdout_match  -> stdin / expected_stdout

    **원본 키를 그대로 보존한다.** 예전에는 stdout 케이스를 input=[stdin]으로
    뭉갰는데, 프론트가 `test.stdin !== undefined`로 렌더링을 분기하기 때문에
    (App.tsx의 formatPublicTest) 뭉개면 "입력 ["5\\n"] → 결과 "8\\n""처럼
    잘못 표시된다. 두 모양을 각자의 필드에 담아 정보 손실을 없앤다.
    """

    category: str = "basic"
    # function_call 전용
    input: list[Any] | None = None
    expected: Any = None
    # stdout_match 전용
    stdin: str | None = None
    expected_stdout: str | None = None


@dataclass(frozen=True)
class ProblemRecord:
    problem_id: str
    title: str
    description: str
    difficulty: str
    concepts: list[str]
    check_type: str
    function_name: str | None
    code_template: str
    public_test_cases: list[TestCase] = field(default_factory=list)
    hidden_test_cases: list[TestCase] = field(default_factory=list)
    # judge 문제 26개 중 23개(stdout_match)에 있다. 문제 화면의 제한 표기에 쓰인다.
    time_limit_sec: float | None = None
    memory_limit_mb: int | None = None

    @property
    def hidden_test_categories(self) -> list[str]:
        """중복 제거된 hidden 카테고리. 입력값이 아니라 카테고리만 나가므로 공개 안전하다."""
        seen: list[str] = []
        for tc in self.hidden_test_cases:
            if tc.category not in seen:
                seen.append(tc.category)
        return seen


def _parse_test_cases(raw: Any, check_type: str) -> list[TestCase]:
    """check_type별로 테스트케이스 키가 다르다. 원본 키를 그대로 보존한다.

    function_call: {"input": [...], "expected": ...}
    stdout_match:  {"stdin": "...", "expected_stdout": "..."}

    키 존재로 판별하지 않고 check_type으로 분기하는 이유: 판별자가 데이터 모양이
    아니라 선언된 타입이어야 새 check_type이 추가될 때 조용히 오분류되지 않는다.
    """
    out: list[TestCase] = []
    for tc in raw or []:
        category = tc.get("category", "basic")
        if check_type == "stdout_match":
            out.append(
                TestCase(
                    category=category,
                    stdin=tc["stdin"],
                    expected_stdout=tc["expected_stdout"],
                )
            )
        else:
            out.append(
                TestCase(
                    category=category,
                    input=tc["input"],
                    expected=tc["expected"],
                )
            )
    return out


def parse_problem(data: dict[str, Any]) -> ProblemRecord:
    """문제 JSON 하나를 파싱한다.

    키 이름은 origin/judge의 파일 기준을 채택했다 (problem_id, code_template) --
    병합 시 rename이 0이 된다. backend_plan §5의 id/starter_code/concepts도 입력으로 받아준다.
    description/difficulty는 judge 파일에 없으므로 부재를 허용한다.

    judge/problems의 stdout_match 문제는 function_name이 없다(stdin/stdout으로
    채점하므로 불필요) -- None으로 둔다. 테스트케이스 키 모양도 check_type별로
    달라서 _parse_test_cases가 분기한다. 이제 judge/problems 26개가 전부 파싱된다.

    difficulty는 judge 파일 26개 전부에 없어서 기본값 BEGINNER가 쓰인다.
    """
    concepts = data.get("concepts") or data.get("concept") or []
    check_type = data.get("check_type", "function_call")
    return ProblemRecord(
        problem_id=data.get("problem_id") or data["id"],
        title=data["title"],
        description=data.get("description", ""),
        difficulty=data.get("difficulty", "BEGINNER"),
        concepts=list(concepts),
        check_type=check_type,
        function_name=data.get("function_name"),
        code_template=data.get("code_template") or data.get("starter_code", ""),
        public_test_cases=_parse_test_cases(data.get("public_test_cases"), check_type),
        hidden_test_cases=_parse_test_cases(data.get("hidden_test_cases"), check_type),
        time_limit_sec=data.get("time_limit_sec"),
        memory_limit_mb=data.get("memory_limit_mb"),
    )


class ProblemRepository:
    def __init__(self, directory: Path) -> None:
        self._dir = directory
        self._by_id: dict[str, ProblemRecord] = {}
        self._order: list[str] = []
        self.reload()

    def reload(self) -> None:
        """디렉터리의 모든 문제 JSON을 읽는다.

        **개별 파일 실패가 저장소 전체를 죽이지 않는다.** 예전에는 한 파일이
        깨지면 예외가 __init__을 뚫고 나가 get_problem_repository()의 의존성
        주입이 실패했고, 그러면 /problems뿐 아니라 /sessions와 /run까지 전부
        500이 됐다. 문제 하나가 잘못된 것과 서비스 전체가 죽는 것은 다른 사건이다.
        """
        self._by_id.clear()
        self._order.clear()
        if not self._dir.exists():
            log.warning("문제 디렉터리가 없습니다: %s", self._dir)
            return
        for path in sorted(self._dir.glob("*.json")):
            try:
                record = parse_problem(json.loads(path.read_text(encoding="utf-8")))
            except Exception:  # noqa: BLE001 - 파일 하나가 전체를 막으면 안 된다
                log.exception("문제 파일을 건너뜁니다: %s", path.name)
                continue
            self._by_id[record.problem_id] = record
            self._order.append(record.problem_id)
        log.info("문제 %d개 로드 (%s)", len(self._order), self._dir)

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
