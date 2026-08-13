"""인증 API + 소유권 격리."""
from __future__ import annotations

from app.auth.security import hash_password, verify_password
from app.models import User


def signup(anon_client, email="new@example.com", password="password123", name="홍길동"):
    return anon_client.post(
        "/auth/signup", json={"name": name, "email": email, "password": password}
    )


# --------------------------------------------------------------------- 회원가입


def test_signup_returns_user_and_token(anon_client):
    r = signup(anon_client)
    assert r.status_code == 201
    body = r.json()
    assert body["user"]["email"] == "new@example.com"
    assert body["user"]["name"] == "홍길동"
    assert body["user"]["nickname"]
    assert body["user"]["acorn_balance"] == 0
    assert body["access_token"]
    assert body["token_type"] == "bearer"


def test_signup_never_returns_password_hash(anon_client):
    """응답 스키마에 password_hash를 담을 필드가 아예 없어야 한다."""
    body = signup(anon_client).text
    assert "password_hash" not in body
    assert "password123" not in body


def test_email_is_normalized_to_lowercase(anon_client, db):
    signup(anon_client, email="MixedCase@Example.COM")
    from sqlmodel import select

    user = db.exec(select(User).where(User.email == "mixedcase@example.com")).first()
    assert user is not None


def test_duplicate_email_is_rejected_case_insensitively(anon_client):
    assert signup(anon_client, email="dup@example.com").status_code == 201
    r = signup(anon_client, email="DUP@example.com")
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "EMAIL_ALREADY_REGISTERED"


def test_short_password_is_rejected(anon_client):
    assert signup(anon_client, password="short").status_code == 422


def test_duplicate_name_gets_distinct_nickname(anon_client):
    a = signup(anon_client, email="a@example.com", name="같은이름").json()
    b = signup(anon_client, email="b@example.com", name="같은이름").json()
    assert a["user"]["nickname"] != b["user"]["nickname"]


# --------------------------------------------------------------------- 로그인


def test_login_returns_token(anon_client):
    signup(anon_client, email="login@example.com", password="password123")
    r = anon_client.post(
        "/auth/login", json={"email": "login@example.com", "password": "password123"}
    )
    assert r.status_code == 200
    assert r.json()["access_token"]


def test_wrong_password_and_unknown_email_give_identical_errors(anon_client):
    """계정 열거를 막는다. 두 경우가 구분되면 이메일 가입 여부를 알아낼 수 있다."""
    signup(anon_client, email="known@example.com", password="password123")

    wrong_pw = anon_client.post(
        "/auth/login", json={"email": "known@example.com", "password": "wrongpassword"}
    )
    unknown = anon_client.post(
        "/auth/login", json={"email": "nobody@example.com", "password": "password123"}
    )

    assert wrong_pw.status_code == unknown.status_code == 401
    assert wrong_pw.json() == unknown.json()


# --------------------------------------------------------------------- /auth/me


def test_me_requires_token(anon_client):
    r = anon_client.get("/auth/me")
    assert r.status_code == 401
    assert r.json()["detail"]["code"] == "NOT_AUTHENTICATED"


def test_me_returns_profile_with_token(anon_client):
    token = signup(anon_client, email="me@example.com").json()["access_token"]
    r = anon_client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json()["email"] == "me@example.com"


def test_garbage_token_is_401_not_500(anon_client):
    for bad in ("Bearer notatoken", "Bearer ", "Basic abc", "notabearer"):
        r = anon_client.get("/auth/me", headers={"Authorization": bad})
        assert r.status_code == 401, bad


# --------------------------------------------------------------------- 해싱


def test_password_hash_roundtrip():
    h = hash_password("password123")
    assert h != "password123"
    assert verify_password("password123", h)
    assert not verify_password("password124", h)


def test_long_passwords_are_not_truncated():
    """bcrypt는 72바이트에서 자른다. pre-hash가 없으면 아래 둘이 같은 해시가 된다."""
    a = "x" * 100 + "A"
    b = "x" * 100 + "B"
    assert not verify_password(b, hash_password(a))


def test_corrupted_hash_fails_closed():
    assert not verify_password("password123", "not-a-bcrypt-hash")


# --------------------------------------------------------------------- 소유권


def test_other_users_session_is_404_not_403(client, anon_client, db):
    """403이면 '그 세션은 존재한다'를 알려주는 셈이다. 존재 자체를 숨긴다."""
    sid = client.post("/sessions", json={"problem_id": "func_sum_list"}).json()["session_id"]

    intruder = signup(anon_client, email="intruder@example.com").json()["access_token"]
    headers = {"Authorization": f"Bearer {intruder}"}

    for path in ("", "/events", "/process-state", "/timeline", "/snapshots"):
        r = anon_client.get(f"/sessions/{sid}{path}", headers=headers)
        assert r.status_code == 404, path
        assert r.json()["detail"]["code"] == "SESSION_NOT_FOUND"


def test_cannot_write_events_to_another_users_session(client, anon_client):
    sid = client.post("/sessions", json={"problem_id": "func_sum_list"}).json()["session_id"]
    intruder = signup(anon_client, email="intruder2@example.com").json()["access_token"]

    r = anon_client.post(
        f"/sessions/{sid}/events",
        json={"events": [{"type": "CODE_SNAPSHOT", "payload": {"code": "x = 1"}}]},
        headers={"Authorization": f"Bearer {intruder}"},
    )
    assert r.status_code == 404


def test_session_is_owned_by_token_holder_not_request_body(client, user):
    """user_id를 body로 보내도 무시된다.

    받아들이면 아무나 남의 이름으로 세션을 만들 수 있고, 그 세션의 채점 결과가
    그 사람의 도토리가 된다.
    """
    r = client.post(
        "/sessions", json={"problem_id": "func_sum_list", "user_id": "someone-else"}
    )
    assert r.status_code == 201
    assert r.json()["user_id"] == user.id


def test_all_session_endpoints_require_auth(anon_client):
    for method, path in [
        ("post", "/sessions"),
        ("get", "/sessions/sess_x"),
        ("get", "/sessions/sess_x/events"),
        ("get", "/sessions/sess_x/process-state"),
        ("get", "/sessions/sess_x/timeline"),
        ("get", "/users/me/profile"),
        ("get", "/users/me/acorns"),
        ("get", "/users/me/progress"),
        ("get", "/users/me/solved-problems"),
    ]:
        r = getattr(anon_client, method)(path, **({"json": {}} if method == "post" else {}))
        assert r.status_code == 401, f"{method} {path}"


def test_agent_decide_requires_auth_and_ownership(client, anon_client):
    """POST /agent/decide 가 남의 세션 컨텍스트를 흘리면 안 된다.

    build_context() 가 학생의 현재 코드와 trace 를 통째로 담아 오므로,
    소유권 검사가 빠지면 session_id 만 알면 학습 내용을 그대로 읽을 수 있다.
    """
    sid = client.post("/sessions", json={"problem_id": "func_sum_list"}).json()["session_id"]

    # 토큰 없음
    assert anon_client.post("/agent/decide", json={"session_id": sid}).status_code == 401

    # 남의 토큰
    intruder = signup(anon_client, email="agentintruder@example.com").json()["access_token"]
    r = anon_client.post(
        "/agent/decide",
        json={"session_id": sid},
        headers={"Authorization": f"Bearer {intruder}"},
    )
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "SESSION_NOT_FOUND"

    # 본인은 통과
    assert client.post("/agent/decide", json={"session_id": sid}).status_code == 200
