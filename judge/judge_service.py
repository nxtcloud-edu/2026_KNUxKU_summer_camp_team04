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
import requests
from docker.errors import DockerException

PROBLEMS_DIR = Path(__file__).parent / "problems"
SANDBOX_IMAGE = "judge-sandbox"

# 문제 JSON에 time_limit_sec/memory_limit_mb가 없을 때 쓰는 기본값.
DEFAULT_TIME_LIMIT_SEC = 5
DEFAULT_MEM_LIMIT_MB = 128

# time_limit_sec은 "테스트케이스 1개당" 제한시간이다 (하네스가 테스트케이스마다
# 서브프로세스를 새로 띄워서 그 안에서 개별적으로 적용함). 컨테이너 전체
# 타임아웃(CONTAINER_*)은 하네스가 어떤 이유로든 멈춰버리는 경우를 잡는
# 안전망일 뿐이라, 테스트 개수만큼 여유를 넉넉히 두고 상한을 건다.
CONTAINER_TIMEOUT_OVERHEAD_SEC = 5
CONTAINER_TIMEOUT_CAP_SEC = 30

PIDS_LIMIT = 64
CPU_LIMIT_NANO = 1_000_000_000  # 1 vCPU로 제한 (무한루프가 호스트 코어를 통째로 잡는 것 방지)

# check_type별로 컨테이너 안에서 돌릴 하네스 스크립트.
# 새 check_type을 추가하려면 harness/에 스크립트를 추가하고 여기 등록만 하면 됨.
HARNESS_BY_CHECK_TYPE = {
    "function_call": "/harness/run_function_call.py",
    "stdout_match": "/harness/run_stdout_match.py",
}


class UnsupportedCheckTypeError(Exception):
    """문제의 check_type에 대응하는 하네스가 없을 때."""


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
    check_type = problem["check_type"]
    if check_type not in HARNESS_BY_CHECK_TYPE:
        raise UnsupportedCheckTypeError(f"지원하지 않는 check_type입니다: {check_type}")

    test_cases = list(problem["public_test_cases"])
    if mode == "submit":
        test_cases += problem.get("hidden_test_cases", [])
    total = len(test_cases)

    time_limit_sec = problem.get("time_limit_sec", DEFAULT_TIME_LIMIT_SEC)
    mem_limit_mb = problem.get("memory_limit_mb", DEFAULT_MEM_LIMIT_MB)

    # 1) 문법 오류는 컨테이너를 띄우기 전에 먼저 걸러낸다 (비용 절감)
    try:
        compile(student_code, "<student_code>", "exec")
    except SyntaxError as e:
        return {"passed": 0, "total": total, "status": "SYNTAX_ERROR", "message": str(e)}

    # 2) 샌드박스 컨테이너에서 실행
    outcome = _run_in_sandbox(check_type, student_code, problem, test_cases, time_limit_sec, mem_limit_mb)

    if outcome["status"] == "TIME_LIMIT":
        return {
            "passed": 0, "total": total, "status": "TIME_LIMIT",
            "message": f"{time_limit_sec}초 내에 실행이 끝나지 않았습니다.",
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


def _run_in_sandbox(
    check_type: str, student_code: str, problem: dict, test_cases: list,
    time_limit_sec: float, mem_limit_mb: float,
) -> dict:
    """격리된 컨테이너에서 학생 코드를 실행하고 결과를 반환한다.

    반환값은 {"status": "OK", "results": [...]} 또는
    {"status": "TIME_LIMIT"} / {"status": "RUNTIME_ERROR", "message": str} 중 하나.
    """
    try:
        client = docker.from_env()
    except DockerException as e:
        return {"status": "RUNTIME_ERROR", "message": f"Docker 데몬에 연결할 수 없습니다: {e}"}

    # time_limit_sec은 하네스가 테스트케이스마다 개별 적용하는 "테스트 1개당" 제한.
    # 컨테이너 전체 타임아웃은 그걸 어기지 않는 선에서, 하네스가 예상 밖으로
    # 멈춰버리는 경우를 잡는 안전망으로만 넉넉하게 잡는다.
    container_timeout = min(
        CONTAINER_TIMEOUT_CAP_SEC,
        time_limit_sec * max(len(test_cases), 1) + CONTAINER_TIMEOUT_OVERHEAD_SEC,
    )
    mem_limit_str = f"{int(mem_limit_mb)}m"

    payload = {"student_code": student_code, "test_cases": test_cases, "time_limit_sec": time_limit_sec}
    if check_type == "function_call":
        payload["function_name"] = problem["function_name"]

    with tempfile.TemporaryDirectory() as tmp_dir:
        payload_path = Path(tmp_dir) / "payload.json"
        payload_path.write_text(json.dumps(payload), encoding="utf-8")

        try:
            container = client.containers.run(
                SANDBOX_IMAGE,
                entrypoint=["python", HARNESS_BY_CHECK_TYPE[check_type]],
                command=["/payload/payload.json"],
                volumes={tmp_dir: {"bind": "/payload", "mode": "ro"}},
                network_disabled=True,
                mem_limit=mem_limit_str,
                memswap_limit=mem_limit_str,  # mem_limit만 걸면 스왑으로 최대 2배까지 우회 가능해서 동일 값으로 스왑 차단
                nano_cpus=CPU_LIMIT_NANO,
                pids_limit=PIDS_LIMIT,
                read_only=True,
                cap_drop=["ALL"],  # 컨테이너 탈출/권한상승 표면 축소 (defense in depth)
                security_opt=["no-new-privileges:true"],
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
                container.wait(timeout=container_timeout)
            except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectionError):
                # 지정 시간 내에 컨테이너가 안 끝난 경우만 TIME_LIMIT으로 처리.
                # 그 외 예외(진짜 버그)까지 여기서 삼켜서 TIME_LIMIT으로 오분류하지 않도록
                # 예외 타입을 좁혀뒀다. 컨테이너는 아직 살아있을 수 있어 강제 kill한다.
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
        if harness_result["error"] == "timeout":
            return {"status": "TIME_LIMIT"}
        return {"status": "RUNTIME_ERROR", "message": harness_result["message"]}

    return {"status": "OK", "results": harness_result["results"]}
