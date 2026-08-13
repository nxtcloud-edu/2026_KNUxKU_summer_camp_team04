"""교육자 API — 역할 게이트, 강의 소유권, 대시보드, 학생 목록·상세.

**가장 중요한 성질은 격리다.** 교수자 A가 교수자 B의 강의나 학생을
볼 수 없어야 하고, 학생은 교육자 API 자체에 닿을 수 없어야 한다.
"""
from __future__ import annotations

import pytest
from sqlmodel import select

from app.enums import CodeVisibility, JudgeStatus, LearningStatus, UserRole
from app.judge import get_judge
from app.judge.interface import JudgeResult
from app.judge.stub import FakeJudge
from app.main import app
from app.models import Organization, User
from tests.fixtures_code import LOOP_V2

ORG_CODE = "KNU-2026"


@pytest.fixture(name="org")
def org_fixture(db):
    o = Organization(name="강원대학교", domain="", invite_code=ORG_CODE)
    db.add(o)
    db.commit()
    db.refresh(o)
    return o


def signup(anon_client, email, *, role="STUDENT", invite_code=None, name="사람"):
    body = {"name": name, "email": email, "password": "password123", "role": role}
    if invite_code:
        body["invite_code"] = invite_code
    return anon_client.post("/auth/signup", json=body)


def token_of(r):
    return r.json()["access_token"]


def h(tok):
    return {"Authorization": f"Bearer {tok}"}


def use_judge(*results: JudgeResult) -> None:
    judge = FakeJudge(list(results))
    app.dependency_overrides[get_judge] = lambda: judge


def accepted(total: int = 5) -> JudgeResult:
    return JudgeResult(status=JudgeStatus.ACCEPTED, passed=total, total=total)


def wrong(passed: int = 1, total: int = 5) -> JudgeResult:
    return JudgeResult(status=JudgeStatus.WRONG_ANSWER, passed=passed, total=total)


# --------------------------------------------------------------------- 가입 게이트


def test_educator_signup_requires_org_invite_code(anon_client, org):
    r = signup(anon_client, "prof@x.com", role="EDUCATOR")
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "INVALID_INVITE_CODE"


def test_educator_signup_with_code_works(anon_client, org):
    r = signup(anon_client, "prof@x.com", role="EDUCATOR", invite_code=ORG_CODE)
    assert r.status_code == 201
    assert r.json()["user"]["role"] == "EDUCATOR"
    assert r.json()["user"]["organization_id"] == org.id


def test_wrong_invite_code_is_rejected(anon_client, org):
    r = signup(anon_client, "prof@x.com", role="EDUCATOR", invite_code="NOPE")
    assert r.status_code == 422


def test_student_signup_needs_no_code(anon_client, org):
    r = signup(anon_client, "s@x.com")
    assert r.status_code == 201
    assert r.json()["user"]["role"] == "STUDENT"


def test_admin_cannot_be_created_by_signup(anon_client, org):
    r = signup(anon_client, "root@x.com", role="ADMIN", invite_code=ORG_CODE)
    assert r.status_code == 422


def test_org_domain_is_enforced_when_set(anon_client, db):
    db.add(Organization(name="고려대", domain="korea.ac.kr", invite_code="KU"))
    db.commit()
    assert signup(anon_client, "a@gmail.com", role="EDUCATOR", invite_code="KU").status_code == 422
    assert signup(anon_client, "a@korea.ac.kr", role="EDUCATOR", invite_code="KU").status_code == 201


# --------------------------------------------------------------------- 역할 게이트


def test_student_cannot_touch_educator_api(anon_client, org):
    tok = token_of(signup(anon_client, "s@x.com"))
    for path in ["/educator/courses"]:
        r = anon_client.get(path, headers=h(tok))
        assert r.status_code == 403
        assert r.json()["detail"]["code"] == "FORBIDDEN"


def test_educator_api_requires_auth(anon_client):
    assert anon_client.get("/educator/courses").status_code == 401


# --------------------------------------------------------------------- 강의


@pytest.fixture(name="educator")
def educator_fixture(anon_client, org):
    r = signup(anon_client, "prof@x.com", role="EDUCATOR", invite_code=ORG_CODE, name="김튜토리")
    return token_of(r)


def make_course(anon_client, tok, title="Python 기초 01", **kw):
    body = {"title": title, "term": "2026 여름학기", **kw}
    return anon_client.post("/educator/courses", json=body, headers=h(tok))


def test_create_and_list_course(anon_client, educator):
    r = make_course(anon_client, educator)
    assert r.status_code == 201
    body = r.json()
    assert body["title"] == "Python 기초 01"
    assert body["invite_code"]
    assert body["code_visibility"] == "SUBMITTED_ONLY"  # 보수적 기본값
    assert body["assigned_problem_count"] == 26  # 배정 안 하면 저장소 전체 (기본 PROBLEMS_DIR = judge/problems)

    listed = anon_client.get("/educator/courses", headers=h(educator)).json()
    assert len(listed) == 1


def test_educator_cannot_see_another_educators_course(anon_client, org, educator):
    cid = make_course(anon_client, educator).json()["id"]
    other = token_of(
        signup(anon_client, "prof2@x.com", role="EDUCATOR", invite_code=ORG_CODE, name="다른교수")
    )

    assert anon_client.get("/educator/courses", headers=h(other)).json() == []
    # 403이 아니라 404 -- 존재 자체를 숨긴다
    for path in ("", "/dashboard", "/students", "/attention"):
        r = anon_client.get(f"/educator/courses/{cid}{path}", headers=h(other))
        assert r.status_code == 404, path
        assert r.json()["detail"]["code"] == "COURSE_NOT_FOUND"


def test_code_visibility_is_chosen_by_educator(anon_client, educator):
    r = make_course(anon_client, educator, code_visibility="LATEST_SNAPSHOT")
    assert r.json()["code_visibility"] == "LATEST_SNAPSHOT"


# --------------------------------------------------------------------- 수강


@pytest.fixture(name="course_with_student")
def course_with_student_fixture(anon_client, educator, org):
    cid = make_course(anon_client, educator).json()["id"]
    stok = token_of(signup(anon_client, "minseo@x.com", name="김민서"))
    r = anon_client.post(
        f"/educator/courses/{cid}/students",
        json={"email": "minseo@x.com"},
        headers=h(educator),
    )
    assert r.status_code == 201
    return cid, stok, r.json()["student_id"]


def test_enroll_and_list_students(anon_client, educator, course_with_student):
    cid, _, sid = course_with_student
    body = anon_client.get(f"/educator/courses/{cid}/students", headers=h(educator)).json()
    assert body["total"] == 1
    assert body["items"][0]["student_id"] == sid
    assert body["items"][0]["name"] == "김민서"


def test_duplicate_enroll_is_409(anon_client, educator, course_with_student):
    cid, _, _ = course_with_student
    r = anon_client.post(
        f"/educator/courses/{cid}/students", json={"email": "minseo@x.com"}, headers=h(educator)
    )
    assert r.status_code == 409


def test_enrolling_an_educator_is_rejected(anon_client, educator, org):
    cid = make_course(anon_client, educator).json()["id"]
    signup(anon_client, "prof3@x.com", role="EDUCATOR", invite_code=ORG_CODE)
    r = anon_client.post(
        f"/educator/courses/{cid}/students", json={"email": "prof3@x.com"}, headers=h(educator)
    )
    assert r.status_code == 404


def test_remove_student(anon_client, educator, course_with_student):
    cid, _, sid = course_with_student
    assert (
        anon_client.delete(
            f"/educator/courses/{cid}/students/{sid}", headers=h(educator)
        ).status_code
        == 204
    )
    assert anon_client.get(f"/educator/courses/{cid}/students", headers=h(educator)).json()["total"] == 0


# --------------------------------------------------------------------- 대시보드


def test_dashboard_of_empty_course_does_not_divide_by_zero(anon_client, educator):
    cid = make_course(anon_client, educator).json()["id"]
    m = anon_client.get(f"/educator/courses/{cid}/dashboard", headers=h(educator)).json()["metrics"]
    assert m["student_count"] == 0
    assert m["average_progress"] == 0
    assert m["completion_rate"] == 0


def test_dashboard_reflects_solved_problems(anon_client, educator, course_with_student):
    cid, stok, _ = course_with_student
    use_judge(accepted())
    sid = anon_client.post(
        "/sessions", json={"problem_id": "func_sum_list"}, headers=h(stok)
    ).json()["session_id"]
    anon_client.post(f"/sessions/{sid}/submit", json={"code": LOOP_V2}, headers=h(stok))

    m = anon_client.get(f"/educator/courses/{cid}/dashboard", headers=h(educator)).json()["metrics"]
    assert m["student_count"] == 1
    assert m["total_attempts"] == 1
    # 배정 안 하면 저장소 전체(26문제) 중 1개 해결 -- round(100/26) = 4
    assert m["average_progress"] == 4
    assert m["completion_rate"] == 4


# --------------------------------------------------------------------- 학생 상세


def test_student_detail_hides_code_by_default(anon_client, educator, course_with_student):
    """기본값 SUBMITTED_ONLY 에서 run 만 한 코드는 보이지 않는다."""
    cid, stok, sid = course_with_student
    use_judge(wrong())
    s = anon_client.post(
        "/sessions", json={"problem_id": "func_sum_list"}, headers=h(stok)
    ).json()["session_id"]
    anon_client.post(f"/sessions/{s}/run", json={"code": LOOP_V2}, headers=h(stok))

    body = anon_client.get(
        f"/educator/courses/{cid}/students/{sid}", headers=h(educator)
    ).json()
    assert body["code_visibility"] == "SUBMITTED_ONLY"
    act = body["recent_activity"][0]
    assert act["code"] is None, "run 만 했는데 작성 중인 코드가 노출됐다"


def test_submitted_code_is_visible_under_submitted_only(anon_client, educator, course_with_student):
    cid, stok, sid = course_with_student
    use_judge(accepted())
    s = anon_client.post(
        "/sessions", json={"problem_id": "func_sum_list"}, headers=h(stok)
    ).json()["session_id"]
    anon_client.post(f"/sessions/{s}/submit", json={"code": LOOP_V2}, headers=h(stok))

    body = anon_client.get(
        f"/educator/courses/{cid}/students/{sid}", headers=h(educator)
    ).json()
    act = body["recent_activity"][0]
    assert act["code"] == LOOP_V2
    assert act["code_kind"] == "SUBMITTED"


def test_latest_snapshot_visibility_shows_working_code(anon_client, educator, org):
    cid = make_course(anon_client, educator, code_visibility="LATEST_SNAPSHOT").json()["id"]
    stok = token_of(signup(anon_client, "jihoon@x.com", name="박지훈"))
    sid = anon_client.post(
        f"/educator/courses/{cid}/students", json={"email": "jihoon@x.com"}, headers=h(educator)
    ).json()["student_id"]

    use_judge(wrong())
    s = anon_client.post(
        "/sessions", json={"problem_id": "func_sum_list"}, headers=h(stok)
    ).json()["session_id"]
    anon_client.post(f"/sessions/{s}/run", json={"code": LOOP_V2}, headers=h(stok))

    body = anon_client.get(
        f"/educator/courses/{cid}/students/{sid}", headers=h(educator)
    ).json()
    assert body["recent_activity"][0]["code"] == LOOP_V2
    assert body["recent_activity"][0]["code_kind"] == "LATEST_SNAPSHOT"


def test_student_not_in_course_is_404(anon_client, educator, course_with_student):
    cid, _, _ = course_with_student
    r = anon_client.get(f"/educator/courses/{cid}/students/user_nobody", headers=h(educator))
    assert r.status_code == 404


# --------------------------------------------------------------------- 도움 필요 판정


def test_struggling_student_appears_in_attention(anon_client, educator, course_with_student):
    cid, stok, sid = course_with_student
    # 같은 문제를 계속 틀린다
    use_judge(*[wrong() for _ in range(6)])
    s = anon_client.post(
        "/sessions", json={"problem_id": "func_sum_list"}, headers=h(stok)
    ).json()["session_id"]
    for _ in range(6):
        anon_client.post(f"/sessions/{s}/run", json={"code": LOOP_V2}, headers=h(stok))

    body = anon_client.get(f"/educator/courses/{cid}/attention", headers=h(educator)).json()
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["student_id"] == sid
    assert item["status"] in ("NEEDS_HELP", "WATCH")
    assert item["risk_score"] > 0
    assert item["reasons"], "왜 위험한지 근거가 비어 있다"


def test_student_list_filter_and_sort(anon_client, educator, course_with_student):
    cid, _, _ = course_with_student
    r = anon_client.get(
        f"/educator/courses/{cid}/students?q=민서&sort=progress_asc", headers=h(educator)
    ).json()
    assert r["total"] == 1

    r2 = anon_client.get(f"/educator/courses/{cid}/students?q=없는이름", headers=h(educator)).json()
    assert r2["total"] == 0


def test_progress_is_recorded_per_course(anon_client, educator, course_with_student, db):
    """채점 결과가 개인 행과 강의 행 **양쪽**에 쌓인다."""
    cid, stok, sid = course_with_student
    use_judge(accepted())
    s = anon_client.post(
        "/sessions", json={"problem_id": "func_sum_list"}, headers=h(stok)
    ).json()["session_id"]
    anon_client.post(f"/sessions/{s}/submit", json={"code": LOOP_V2}, headers=h(stok))

    from app.models import UserProblemProgress

    rows = db.exec(
        select(UserProblemProgress).where(UserProblemProgress.user_id == sid)
    ).all()
    course_ids = {r.course_id for r in rows}
    assert "" in course_ids, "개인 학습 행이 없다"
    assert cid in course_ids, "강의 행이 없다"


def test_acorns_awarded_once_even_with_multiple_course_rows(anon_client, educator, course_with_student):
    """강의 행이 여러 개여도 도토리는 한 번만 나간다."""
    cid, stok, _ = course_with_student
    use_judge(accepted())
    s = anon_client.post(
        "/sessions", json={"problem_id": "func_sum_list"}, headers=h(stok)
    ).json()["session_id"]
    anon_client.post(f"/sessions/{s}/submit", json={"code": LOOP_V2}, headers=h(stok))

    assert anon_client.get("/users/me/acorns", headers=h(stok)).json()["balance"] == 10


def test_seeded_emails_are_actually_loginable():
    """시드 스크립트가 만드는 계정이 로그인 API 를 통과해야 한다.

    모델을 직접 쓰는 스크립트는 EmailStr 검증을 우회하므로, @demo.local 같은
    예약 TLD 를 쓰면 계정은 만들어지지만 **로그인만 조용히 막힌다.**
    """
    from pydantic import TypeAdapter
    from pydantic import EmailStr

    from scripts.seed_org import EDUCATOR_EMAIL, STUDENT_EMAILS

    adapter = TypeAdapter(EmailStr)
    for email in [EDUCATOR_EMAIL, *STUDENT_EMAILS]:
        adapter.validate_python(email)  # 실패하면 여기서 터진다
