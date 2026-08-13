from __future__ import annotations

from tests.fixtures_code import LOOP_V2, LOOP_V3


def create(client) -> str:
    return client.post("/sessions", json={"problem_id": "func_sum_list"}).json()[
        "session_id"
    ]


def edit(client, sid: str, code: str):
    client.post(
        f"/sessions/{sid}/events",
        json={"events": [{"type": "CODE_SNAPSHOT", "payload": {"code": code}}]},
    )


def test_list_snapshots_omits_code(client):
    sid = create(client)
    edit(client, sid, LOOP_V2)
    body = client.get(f"/sessions/{sid}/snapshots").json()
    assert [s["version"] for s in body] == [1, 2]
    assert all("code" not in s for s in body)


def test_get_snapshot_includes_code(client):
    sid = create(client)
    edit(client, sid, LOOP_V2)
    body = client.get(f"/sessions/{sid}/snapshots/2").json()
    assert body["code"] == LOOP_V2
    assert body["parent_version"] == 1
    assert body["session_id"] == sid


def test_snapshot_v1_is_the_problem_template(client):
    """Process Replay의 기준점."""
    sid = create(client)
    body = client.get(f"/sessions/{sid}/snapshots/1").json()
    assert body["code"].startswith("def sum_list(arr):")
    assert body["parent_version"] is None


def test_unknown_version_returns_404(client):
    sid = create(client)
    r = client.get(f"/sessions/{sid}/snapshots/99")
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "SNAPSHOT_NOT_FOUND"


def test_diff_against_previous_version(client):
    sid = create(client)
    edit(client, sid, LOOP_V2)
    edit(client, sid, LOOP_V3)

    body = client.get(f"/sessions/{sid}/snapshots/3/diff").json()
    assert body["from_version"] == 2
    assert body["to_version"] == 3
    assert body["changed_lines"] == [3]
    assert body["primary_region"] == "loop"
    assert body["unified_diff"]


def test_diff_against_arbitrary_version(client):
    sid = create(client)
    edit(client, sid, LOOP_V2)
    edit(client, sid, LOOP_V3)

    body = client.get(f"/sessions/{sid}/snapshots/3/diff", params={"from": 1}).json()
    assert body["from_version"] == 1
    assert body["change_size"] > 2  # 템플릿 대비면 훨씬 크다


def test_diff_with_unknown_from_version_returns_404(client):
    sid = create(client)
    edit(client, sid, LOOP_V2)
    r = client.get(f"/sessions/{sid}/snapshots/2/diff", params={"from": 99})
    assert r.status_code == 404
