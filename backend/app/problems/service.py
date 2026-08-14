"""문제 저장소.

문제는 DB가 아니라 *.json 파일이 진실이다 (models.py 상단 주석 참조).
파일을 시작 시 읽어 메모리에 들고 있는다.

**두 디렉터리를 읽는다:**
  1. `PROBLEMS_DIR` — 사람이 만든 큐레이션 문제 (읽기 전용)
  2. `GENERATED_PROBLEMS_DIR` — 복습 문제 생성 agent가 만든 문제 (런타임에 늘어남)

둘을 한 저장소로 합치는 게 이 설계의 핵심이다. `get()`/`exists()`/`list()`
하나로 두 종류가 똑같이 풀리므로 세션 생성·채점·agent context·진도 기록은
"이 문제가 생성된 것인지"를 **알 필요조차 없다** (호출부 14곳이 그대로 동작한다).

여기서 파싱한 ProblemRecord는 **라우터 경계를 넘지 않는다.**
hidden test case는 이 dataclass 안에만 존재하고, 응답 스키마(ProblemDetail)에는
그걸 담을 수 있는 필드가 아예 없다. 유출 방지가 절차가 아니라 구조인 이유다.
"""
from __future__ import annotations

import json
import logging
import re
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
    def __init__(self, directory: Path, generated_directory: Path | None = None) -> None:
        self._dir = directory
        self._generated_dir = generated_directory
        self._by_id: dict[str, ProblemRecord] = {}
        self._order: list[str] = []
        # 생성 문제의 id 집합. `list()`가 이들을 문제 목록에서 빼는 데 쓴다
        # (복습 문제는 개인 것이라 전체 목록에 뜨면 안 된다 — 아래 list() 참고).
        self._generated_ids: set[str] = set()
        self.reload()

    # ---------------------------------------------------------------- 로딩

    def _load_dir(self, directory: Path, *, generated: bool) -> int:
        """디렉터리 하나를 읽어 메모리에 등록한다. 등록한 개수를 반환.

        **개별 파일 실패가 저장소 전체를 죽이지 않는다.** 예전에는 한 파일이
        깨지면 예외가 __init__을 뚫고 나가 get_problem_repository()의 의존성
        주입이 실패했고, 그러면 /problems뿐 아니라 /sessions와 /run까지 전부
        500이 됐다. 문제 하나가 잘못된 것과 서비스 전체가 죽는 것은 다른 사건이다.
        """
        if not directory.exists():
            return 0
        loaded = 0
        for path in sorted(directory.glob("*.json")):
            try:
                record = parse_problem(json.loads(path.read_text(encoding="utf-8")))
            except Exception:  # noqa: BLE001 - 파일 하나가 전체를 막으면 안 된다
                log.exception("문제 파일을 건너뜁니다: %s", path.name)
                continue
            self._register(record, generated=generated)
            loaded += 1
        return loaded

    def _register(self, record: ProblemRecord, *, generated: bool) -> None:
        if record.problem_id not in self._by_id:
            self._order.append(record.problem_id)
        self._by_id[record.problem_id] = record
        if generated:
            self._generated_ids.add(record.problem_id)

    def reload(self) -> None:
        """두 디렉터리(큐레이션 + 생성)의 모든 문제 JSON을 읽는다."""
        self._by_id.clear()
        self._order.clear()
        self._generated_ids.clear()
        if not self._dir.exists():
            log.warning("문제 디렉터리가 없습니다: %s", self._dir)
        curated = self._load_dir(self._dir, generated=False)
        generated = (
            self._load_dir(self._generated_dir, generated=True)
            if self._generated_dir is not None
            else 0
        )
        log.info(
            "문제 %d개 로드 (큐레이션 %d, 생성 %d)", curated + generated, curated, generated
        )

    def add_generated(self, problem_json: dict[str, Any], problem_id: str) -> ProblemRecord:
        """검증을 통과한 생성 문제를 파일로 쓰고 **즉시** 메모리에 등록한다.

        파일만 쓰고 끝내면 다음 재기동 전까지 `get()`이 못 찾는다 — 학생은
        방금 만들어진 문제를 바로 풀려고 하므로 그건 곧 404다. 그래서 쓰기와
        등록을 여기서 한 트랜잭션처럼 묶는다.
        """
        if self._generated_dir is None:
            raise RuntimeError("생성 문제 디렉터리가 설정되지 않았습니다.")
        self._generated_dir.mkdir(parents=True, exist_ok=True)

        payload = {**problem_json, "problem_id": problem_id}
        path = self._generated_dir / f"{problem_id}.json"
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        record = parse_problem(payload)
        self._register(record, generated=True)
        return record

    # ---------------------------------------------------------------- 조회

    def list(self) -> list[ProblemRecord]:
        """**큐레이션 문제만** 반환한다.

        생성 문제를 빼는 이유: 복습 문제는 특정 학생 한 명을 위해 만들어진
        것이라 전체 문제 목록/교육자 대시보드의 분모에 섞이면 안 된다.
        (`educator/service.py`의 진도율이 `repo.list()`를 분모로 쓴다 — 여기
        생성 문제가 들어가면 남이 만든 복습 문제 때문에 다른 학생의 진도율이
        떨어진다.) 학생이 자기 복습 문제를 보는 건 `/users/me/review-problems`다.
        """
        return [
            self._by_id[pid] for pid in self._order if pid not in self._generated_ids
        ]

    def get(self, problem_id: str) -> ProblemRecord:
        record = self._by_id.get(problem_id)
        if record is None:
            record = self._reload_generated_on_miss(problem_id)
        if record is None:
            raise ProblemNotFound(problem_id)
        return record

    def exists(self, problem_id: str) -> bool:
        return (
            problem_id in self._by_id
            or self._reload_generated_on_miss(problem_id) is not None
        )

    def _reload_generated_on_miss(self, problem_id: str) -> ProblemRecord | None:
        """메모리에 없는 id면 생성 디렉터리에서 그 파일 하나만 늦게 읽어본다.

        이 저장소는 프로세스별 싱글턴(`@lru_cache`)이라, uvicorn을 워커 여러
        개로 띄우면 워커 A가 `add_generated()`로 만든 문제를 워커 B는 모른다.
        그 상태로 학생 요청이 B에 걸리면 방금 만든 복습 문제가 404가 된다.
        여기서 파일을 직접 확인해 그 창을 막는다.

        디렉터리 전체 재스캔이 아니라 **해당 파일 하나만** 본다 — 없는 id를
        반복 조회해도 비용이 stat 한 번이다.
        """
        if self._generated_dir is None:
            return None
        # problem_id가 파일명이 되므로 경로 조작을 막는다. 생성 id는 우리가
        # 만들지만(genp 접두어 + uuid), 이 함수는 사용자가 준 문자열로도 불린다.
        if not _SAFE_PROBLEM_ID.fullmatch(problem_id):
            return None
        path = self._generated_dir / f"{problem_id}.json"
        if not path.is_file():
            return None
        try:
            record = parse_problem(json.loads(path.read_text(encoding="utf-8")))
        except Exception:  # noqa: BLE001
            log.exception("생성 문제 파일을 읽지 못했습니다: %s", path.name)
            return None
        self._register(record, generated=True)
        return record


#: 파일명으로 그대로 쓰이므로 경로 구분자/상위 이동이 섞이면 안 된다.
_SAFE_PROBLEM_ID = re.compile(r"[A-Za-z0-9_\-]{1,64}")


@lru_cache
def get_problem_repository() -> ProblemRepository:
    settings = get_settings()
    return ProblemRepository(
        settings.problems_path, settings.generated_problems_path
    )
