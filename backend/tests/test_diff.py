from __future__ import annotations

import pytest

from app.enums import RegionTag
from app.trace.diff import compute_diff, tag_line
from tests.fixtures_code import BROKEN_MID_EDIT, LOOP_V2, LOOP_V3


def d(old: str | None, new: str):
    return compute_diff(old, new, from_version=1, to_version=2)


def test_no_change():
    r = d(LOOP_V2, LOOP_V2)
    assert r.change_ratio == 0.0
    assert r.changed_lines == []
    assert r.deleted_lines == []
    assert r.change_size == 0
    assert r.summary == "변경 없음"


def test_single_line_replace():
    r = d(LOOP_V2, LOOP_V3)
    assert r.changed_lines == [3]  # for 줄만 바뀐다
    assert r.added_line_count == 1
    assert r.deleted_line_count == 1
    assert r.primary_region == RegionTag.LOOP.value


def test_pure_insert_has_no_deleted_lines():
    r = d("a = 1", "a = 1\nb = 2")
    assert r.deleted_lines == []
    assert r.added_line_count == 1
    assert r.deleted_line_count == 0


def test_pure_delete_has_no_changed_lines():
    r = d("a = 1\nb = 2", "a = 1")
    assert r.changed_lines == []
    assert r.deleted_line_count == 1
    assert r.added_line_count == 0


def test_first_snapshot_against_none():
    r = compute_diff(None, "a = 1\nb = 2", from_version=None, to_version=1)
    assert r.change_ratio == 1.0
    assert r.changed_lines == [1, 2]
    assert r.from_version is None


def test_trailing_whitespace_only_change_is_not_a_change():
    r = d("total = 0", "total = 0   ")
    assert r.change_ratio == 0.0


def test_indentation_change_is_a_change():
    """Python에서 들여쓰기 변경은 진짜 버그다. 반드시 잡혀야 한다."""
    r = d("if x:\n    y = 1", "if x:\n        y = 1")
    assert r.change_size > 0


def test_deleted_lines_are_tagged_too():
    """for 줄을 지운 것도 loop 편집이다."""
    r = d("for i in range(3):\n    pass", "pass")
    assert RegionTag.LOOP.value in r.region_tags


def test_syntactically_invalid_code_does_not_raise():
    """ast 대신 regex를 쓴 이유를 실행 가능하게 만든 테스트.

    편집 중이라 괄호가 안 맞는 코드도 loop로 태깅되어야 한다.
    ast.parse였다면 모듈 전체가 SyntaxError라 태그가 0개가 되고
    same_region_edit_count가 조용히 0을 읽는다 -- 시나리오 2가 의존하는 그 시퀀스 내내.
    """
    r = d(LOOP_V2, BROKEN_MID_EDIT)
    assert r.primary_region == RegionTag.LOOP.value
    assert r.change_size > 0


def test_deterministic_primary_region_under_tie(monkeypatch):
    """동점이면 _PRIORITY 순서로 결정된다 (loop > condition)."""
    old = "x = 1"
    new = "for i in range(3):\n    pass\nif x:\n    pass"
    r = d(old, new)
    # loop 1줄 + condition 1줄이 동점 -> _PRIORITY의 loop가 이긴다
    assert r.primary_region == RegionTag.LOOP.value


def test_change_ratio_denominator_is_max_of_both_sides():
    old = "\n".join(f"line{i}" for i in range(10))
    new = old + "\nline10"
    r = d(old, new)
    assert r.change_ratio == pytest.approx(1 / 11, abs=1e-3)


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("def sum_list(arr):", RegionTag.FUNCTION_DEF),
        ("class Foo:", RegionTag.FUNCTION_DEF),
        ("@decorator", RegionTag.FUNCTION_DEF),
        ("def f(x): return x", RegionTag.FUNCTION_DEF),  # return보다 우선
        ("for i in range(len(arr)):", RegionTag.LOOP),
        ("while i < n:", RegionTag.LOOP),
        ("    n = len(range(5))", RegionTag.LOOP),  # range( 포함
        ("for i, v in enumerate(arr):", RegionTag.LOOP),
        ("if x > 0:", RegionTag.CONDITION),
        ("elif x < 0:", RegionTag.CONDITION),
        ("else:", RegionTag.CONDITION),
        ("    return total", RegionTag.RETURN),
        ("    yield x", RegionTag.RETURN),
        ("    total += x", RegionTag.ACCUMULATOR),
        ("    total = total + x", RegionTag.ACCUMULATOR),
        ("    count -= 1", RegionTag.ACCUMULATOR),
        ("total = 0", RegionTag.INITIALIZATION),
        ("result = []", RegionTag.INITIALIZATION),
        ("flag = False", RegionTag.INITIALIZATION),
        ("value = None", RegionTag.INITIALIZATION),
        ("x = compute(y)", RegionTag.OTHER),  # RHS가 리터럴이 아니다
        ("x = a + b", RegionTag.OTHER),
        ("", RegionTag.OTHER),
        ("    # 여기에 코드를 작성하세요", RegionTag.OTHER),  # 주석 제거 후 빈 줄
        ("    pass", RegionTag.OTHER),
    ],
)
def test_tag_line_matrix(line: str, expected: RegionTag):
    assert tag_line(line) is expected


def test_comment_containing_keyword_is_ignored():
    """주석 안의 'for'가 loop로 오인되면 안 된다."""
    assert tag_line("x = 1  # for loop 준비") is RegionTag.INITIALIZATION


def test_string_containing_keyword_is_ignored():
    """문자열 리터럴 안의 'for'/'range'가 loop로 새면 안 된다.

    문자열이 ''로 치환되므로 `msg = ''`가 되어 initialization으로 읽힌다 -- 그게 맞다.
    중요한 건 LOOP가 아니라는 것.
    """
    assert tag_line('msg = "for i in range"') is RegionTag.INITIALIZATION
    assert tag_line('    print("for i in range(5)")') is RegionTag.OTHER


def test_unified_diff_is_truncated():
    old = "\n".join(f"a{i}" for i in range(500))
    new = "\n".join(f"b{i}" for i in range(500))
    r = d(old, new)
    assert len(r.unified_diff.splitlines()) <= 200
