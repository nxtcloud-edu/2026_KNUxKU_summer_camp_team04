"""코드 diff + 영역 태깅. 순수 모듈 -- DB도, app.enums 외의 app.* import도 없다.

왜 ast가 아니라 regex인가
--------------------------
우리가 태깅하는 건 **편집 중인 학생 코드**이고, 상당 비율이 문법적으로 무효다.
그리고 그 무효성은 노이즈가 아니라 우리가 관찰하려는 바로 그 모집단이다.
range()에서 막힌 학생이 `for i in range(len(arr) -`까지 치고 멈춘 스냅샷이야말로
loop로 태깅되어야 하는 스냅샷이다.

ast.parse는 나쁜 줄이 아니라 **모듈 전체**에 SyntaxError를 던진다. 괄호 하나가
안 맞으면 파일 전체가 태그 0개다. 게다가 조용하다 -- try/except SyntaxError로 감싸
빈 리스트를 반환하게 될 텐데, 그러면 same_region_edit_count가 0을 읽는다.
하필 시나리오 2(3/5 -> 3/5 -> 3/5 + 반복 loop 수정)가 의존하는 그 편집 시퀀스 내내.
테스트는 초록인데 데모가 실패한다.

부수적 이유: ast는 여러 줄 표현식 안의 줄에 대해 줄 단위 태그를 주지 못하고,
스냅샷마다 전체 파싱 비용이 들며, same_region_edit_count에 필요한 건 애초에
"같은 종류를 또 건드렸나"라는 거친 버킷이지 식별자 해석이 아니다.
regex의 진짜 약점(for 안의 if를 최상위 if와 구분 못 함)은 그 질문과 무관하다.
"""
from __future__ import annotations

import difflib
import re
from collections import Counter
from dataclasses import dataclass

from app.enums import RegionTag

_COMMENT = re.compile(r"#.*$")
_STRING = re.compile(r"('''|\"\"\"|'[^']*'|\"[^\"]*\")")

# 순서가 설계다. 위에서부터 처음 매칭되는 것이 그 줄의 태그다.
_RULES: list[tuple[re.Pattern[str], RegionTag]] = [
    # function_def가 첫 번째: `def f(x): return x`가 return으로 태깅되면 안 된다.
    (re.compile(r"^\s*(?:async\s+)?def\s|^\s*class\s|^\s*@\w"), RegionTag.FUNCTION_DEF),
    # loop가 condition보다 위: for 헤더 안의 편집이 range( 덕분에 loop 맥락을 유지한다.
    (re.compile(r"^\s*(?:for|while)\b|\brange\s*\(|\benumerate\s*\("), RegionTag.LOOP),
    (re.compile(r"^\s*(?:if|elif|else|match|case)\b"), RegionTag.CONDITION),
    (re.compile(r"^\s*(?:return|yield)\b"), RegionTag.RETURN),
    # accumulator가 initialization보다 위: `total += x`는 대입이 아니다.
    (re.compile(r"^\s*[\w.\[\]]+\s*(?:\+=|-=|\*=|/=|//=|%=|\|=|&=)"), RegionTag.ACCUMULATOR),
    (re.compile(r"^\s*(\w+)\s*=\s*\1\s*[-+*/]"), RegionTag.ACCUMULATOR),  # total = total + x
    # initialization은 RHS가 **리터럴일 때만**. `total = 0`은 초기화, `x = compute(y)`는 other.
    # 여기서 정확한 게 중요한 이유: initialization은 agent가 실제로 행동할 개념 이름이다.
    (
        re.compile(
            r"^\s*[\w.\[\]]+\s*=\s*"
            r"(?:-?\d+(?:\.\d+)?|\[\s*\]|\{\s*\}|\(\s*\)|''|\"\"|None|True|False)\s*$"
        ),
        RegionTag.INITIALIZATION,
    ),
]

# primary_region 동점 시의 결정론적 tie-break 순서.
# Counter.most_common()은 삽입 순서로 동점을 깨는데, 그건 테스트를 걸 만한 보장이 아니다.
_PRIORITY: list[RegionTag] = [
    RegionTag.LOOP,
    RegionTag.CONDITION,
    RegionTag.ACCUMULATOR,
    RegionTag.INITIALIZATION,
    RegionTag.RETURN,
    RegionTag.FUNCTION_DEF,
    RegionTag.OTHER,
]

_REGION_LABEL: dict[RegionTag, str] = {
    RegionTag.LOOP: "반복문",
    RegionTag.CONDITION: "조건문",
    RegionTag.ACCUMULATOR: "누적 변수",
    RegionTag.INITIALIZATION: "초기화",
    RegionTag.RETURN: "반환",
    RegionTag.FUNCTION_DEF: "함수 정의",
    RegionTag.OTHER: "기타",
}


def tag_line(line: str) -> RegionTag:
    """한 줄의 영역 태그. 절대 예외를 던지지 않는다 (문법 오류 코드도 입력이다)."""
    stripped = _STRING.sub("''", _COMMENT.sub("", line))
    if not stripped.strip():
        return RegionTag.OTHER
    for pattern, tag in _RULES:
        if pattern.search(stripped):
            return tag
    return RegionTag.OTHER


@dataclass(frozen=True)
class DiffResult:
    from_version: int | None
    to_version: int
    changed_lines: list[int]  # NEW 코드 기준 1-based
    deleted_lines: list[int]  # OLD 코드 기준 1-based
    added_line_count: int
    deleted_line_count: int
    change_size: int  # added + deleted
    # 분모가 max(len(old), len(new))이고 분자는 added+deleted라서 1.0을 넘을 수 있다.
    # (예: 3줄 파일의 2줄을 4줄로 교체 -> (4+2)/5 = 1.2)
    # 전체 재작성이 1.0 근처, 긴 파일에 한 줄 추가가 0에 가깝기만 하면 되므로 clamp하지 않는다.
    change_ratio: float  # 0.0 ~ 2.0
    region_tags: list[str]  # 정렬된 distinct
    primary_region: str
    summary: str
    unified_diff: str  # replay/데모용, 200줄로 절단


def _normalize(code: str | None) -> list[str]:
    """줄 끝 공백만 제거. 들여쓰기는 Python에서 의미가 있으므로 보존한다.

    - splitlines(): Windows 클립보드의 \\r\\n을 처리하고 유령 후행 빈 줄을 만들지 않는다.
    - rstrip(): 후행 공백만의 diff는 노이즈지만, 들여쓰기 변경은 진짜 Python 버그라
      반드시 변경으로 잡혀야 한다.
    """
    if code is None:
        return []
    return [ln.rstrip() for ln in code.splitlines()]


def _primary(tags: list[RegionTag]) -> RegionTag:
    if not tags:
        return RegionTag.OTHER
    counts = Counter(tags)
    top = max(counts.values())
    for tag in _PRIORITY:
        if counts.get(tag, 0) == top:
            return tag
    return RegionTag.OTHER


def _summary(
    primary: RegionTag, added: int, deleted: int, changed_lines: list[int]
) -> str:
    if added == 0 and deleted == 0:
        return "변경 없음"
    label = _REGION_LABEL[primary]
    if added and not deleted:
        what = f"{added}줄 추가"
    elif deleted and not added:
        what = f"{deleted}줄 삭제"
    else:
        what = f"{added}줄 추가 / {deleted}줄 삭제"
    where = f" (line {changed_lines[0]})" if len(changed_lines) == 1 else ""
    return f"{label} 영역 {what}{where}"


def compute_diff(
    old_code: str | None,
    new_code: str,
    *,
    from_version: int | None,
    to_version: int,
) -> DiffResult:
    old_lines = _normalize(old_code)
    new_lines = _normalize(new_code)

    # autojunk=False: SequenceMatcher의 autojunk 휴리스틱은 200개 이상 시퀀스에서
    # 1% 넘게 등장하는 원소를 "junk"로 보고 매칭에서 뺀다. 빈 줄이나 `    pass`가 많은
    # 파일에서 opcode를 조용히 왜곡한다. 공짜 보험.
    sm = difflib.SequenceMatcher(a=old_lines, b=new_lines, autojunk=False)

    changed: list[int] = []
    deleted: list[int] = []
    added_n = 0
    deleted_n = 0
    tags: list[RegionTag] = []

    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            continue
        if op in ("replace", "insert"):
            changed.extend(range(j1 + 1, j2 + 1))
            added_n += j2 - j1
            tags.extend(tag_line(new_lines[k]) for k in range(j1, j2))
        if op in ("replace", "delete"):
            deleted.extend(range(i1 + 1, i2 + 1))
            deleted_n += i2 - i1
            # 삭제된 줄도 태깅한다: for 줄을 지운 것도 loop 편집이다.
            tags.extend(tag_line(old_lines[k]) for k in range(i1, i2))

    change_size = added_n + deleted_n
    # 분모가 max(old, new)인 이유: 전체 재작성은 1.0에 수렴하고,
    # 긴 파일에 한 줄 덧붙이는 건 작게 남는다.
    denom = max(len(old_lines), len(new_lines), 1)
    ratio = round(change_size / denom, 4)

    # primary_region은 other가 아닌 태그를 우선한다. 안 그러면 빈 줄이 섞인
    # 3줄짜리 diff 안의 1줄 loop 편집이 other로 읽힌다.
    meaningful = [t for t in tags if t is not RegionTag.OTHER]
    primary = _primary(meaningful or tags)

    unified = list(
        difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=f"v{from_version}" if from_version is not None else "empty",
            tofile=f"v{to_version}",
            lineterm="",
            n=2,
        )
    )[:200]

    return DiffResult(
        from_version=from_version,
        to_version=to_version,
        changed_lines=changed,
        deleted_lines=deleted,
        added_line_count=added_n,
        deleted_line_count=deleted_n,
        change_size=change_size,
        change_ratio=ratio,
        region_tags=sorted({t.value for t in tags}),
        primary_region=primary.value,
        summary=_summary(primary, added_n, deleted_n, changed),
        unified_diff="\n".join(unified),
    )


def region_label(region: str) -> str:
    """evidence 문자열용 한국어 라벨."""
    try:
        return _REGION_LABEL[RegionTag(region)]
    except ValueError:
        return region
