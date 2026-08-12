"""Judge 서비스 핵심 로직.

학생이 제출한 Python 코드를 Docker 컨테이너 안에서 격리 실행하고,
문제별 Public/Hidden 테스트케이스로 채점한다.

API 응답 스펙, 문제 JSON 스키마, 보안/격리 옵션의 근거는 CLAUDE.md 참고.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import docker
from docker.errors import DockerException

PROBLEMS_DIR = Path(__file__).parent / "problems"
SANDBOX_IMAGE = "judge-sandbox"
TIMEOUT_SEC = 5
MEM_LIMIT = "128m"
PIDS_LIMIT = 64


class ProblemNotFoundError(Exception):
    """요청한 problem_id에 해당하는 문제 JSON이 없을 때."""


def load_problem(problem_id: str) -> dict:
    path = PROBLEMS_DIR / f"{problem_id}.json"
    if not path.exists():
        raise ProblemNotFoundError(f"문제를 찾을 수 없습니다: {problem_id}")
    return json.loads(path.read_text(encoding="utf-8"))


def list_all_problems() -> list:
    """프론트 API용 - 테스트케이스/코드 템플릿은 제외한 메타데이터만 반환."""
    problems = []
    for path in sorted(PROBLEMS_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        problems.append({
            "problem_id": data["problem_id"],
            "title": data["title"],
            "concept": data.get("concept", []),
        })
    return problems


def run_judge(student_code: str, problem_id: str, mode: str = "run") -> dict:
    """학생 코드를 채점한다.

    mode="run"    -> public_test_cases만 채점
    mode="submit" -> public_test_cases + hidden_test_cases 전체 채점
    """
    problem = load_problem(problem_id)
    test_cases = list(problem["public_test_cases"])
    if mode == "submit":
        test_cases += problem.get("hidden_test_cases", [])
    total = len(test_cases)

    # 1) 문법 오류는 컨테이너를 띄우기 전에 먼저 걸러낸다 (비용 절감)
    try:
        compile(student_code, "<student_code>", "exec")
    except SyntaxError as e:
        return {"passed": 0, "total": total, "status": "SYNTAX_ERROR", "message": str(e)}

    # 2) 샌드박스 컨테이너에서 실행
    outcome = _run_in_sandbox(student_code, problem["function_name"], test_cases)

    if outcome["status"] == "TIME_LIMIT":
        return {
            "passed": 0, "total": total, "status": "TIME_LIMIT",
            "message": f"{TIMEOUT_SEC}초 내에 실행이 끝나지 않았습니다.",
        }
    if outcome["status"] == "RUNTIME_ERROR":
        return {
            "passed": 0, "total": total, "status": "RUNTIME_ERROR",
            "message": outcome["message"],
        }

    results = outcome["results"]
    passed = sum(1 for r in results if r["passed"])
    status = "ACCEPTED" if passed == total else "WRONG_ANSWER"

    response = {"passed": passed, "total": total, "status": status}
    if mode == "submit" and status == "WRONG_ANSWER":
        response["failed_categories"] = [r["category"] for r in results if not r["passed"]]
    return response


def _run_in_sandbox(student_code: str, function_name: str, test_cases: list) -> dict:
    """격리된 컨테이너에서 학생 코드를 실행하고 결과를 반환한다.

    반환값은 {"status": "OK", "results": [...]} 또는
    {"status": "TIME_LIMIT"} / {"status": "RUNTIME_ERROR", "message": str} 중 하나.
    """
    try:
        client = docker.from_env()
    except DockerException as e:
        return {"status": "RUNTIME_ERROR", "message": f"Docker 데몬에 연결할 수 없습니다: {e}"}

    payload = {
        "student_code": student_code,
        "function_name": function_name,
        "test_cases": test_cases,
    }

    with tempfile.TemporaryDirectory() as tmp_dir:
        payload_path = Path(tmp_dir) / "payload.json"
        payload_path.write_text(json.dumps(payload), encoding="utf-8")

        try:
            container = client.containers.run(
                SANDBOX_IMAGE,
                command=["/payload/payload.json"],
                volumes={tmp_dir: {"bind": "/payload", "mode": "ro"}},
                network_disabled=True,
                mem_limit=MEM_LIMIT,
                pids_limit=PIDS_LIMIT,
                read_only=True,
                detach=True,
            )
        except DockerException as e:
            return {
                "status": "RUNTIME_ERROR",
                "message": (
                    f"샌드박스 컨테이너를 실행할 수 없습니다 ({e}). "
                    f"`docker build -t {SANDBOX_IMAGE} .`를 먼저 실행했는지 확인하세요."
                ),
            }

        try:
            try:
                container.wait(timeout=TIMEOUT_SEC)
            except Exception:
                # docker wait이 타임아웃돼도 컨테이너는 계속 살아있을 수 있어 강제 kill
                container.kill()
                return {"status": "TIME_LIMIT"}

            logs = container.logs().decode("utf-8", errors="replace").strip()
        finally:
            container.remove(force=True)

    if not logs:
        return {"status": "RUNTIME_ERROR", "message": "컨테이너에서 출력이 없습니다."}

    try:
        harness_result = json.loads(logs.splitlines()[-1])
    except json.JSONDecodeError:
        return {"status": "RUNTIME_ERROR", "message": logs}

    if "error" in harness_result:
        return {"status": "RUNTIME_ERROR", "message": harness_result["message"]}

    return {"status": "OK", "results": harness_result["results"]}
