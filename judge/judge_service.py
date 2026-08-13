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

# check_type별로 "정답과 비교하지 않고 실제 출력만 캡처"하는 하네스.
# 문제 생성 파이프라인이 레퍼런스 정답 코드를 실행해 expected 값을 확정할 때 씀
# (capture_reference_outputs 참고). 채점용 HARNESS_BY_CHECK_TYPE와는 별도.
CAPTURE_HARNESS_BY_CHECK_TYPE = {
    "function_call": "/harness/run_capture_call.py",
    "stdout_match": "/harness/run_capture_stdout.py",
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


def get_problem_detail(problem_id: str) -> dict:
    """프론트 API용 - 문제 풀이 화면에 필요한 정보(지문/코드 템플릿/공개
    테스트케이스)만 반환. hidden_test_cases는 절대 포함하지 않는다
    (정답이 노출되면 안 되니까)."""
    problem = load_problem(problem_id)
    return {k: v for k, v in problem.items() if k != "hidden_test_cases"}


def run_judge(student_code: str, problem_id: str, mode: str = "run") -> dict:
    """학생 코드를 채점한다.

    mode="run"    -> public_test_cases만 채점
    mode="submit" -> public_test_cases + hidden_test_cases 전체 채점
    """
    return run_judge_for_problem(student_code, load_problem(problem_id), mode)


def run_judge_for_problem(student_code: str, problem: dict, mode: str = "run") -> dict:
    """`run_judge`의 핵심 로직. 문제를 problem_id가 아니라 dict로 직접 받는다.

    problems/*.json으로 아직 저장되지 않은 문제(예: agent가 생성한 후보 문제를
    파일로 쓰기 전에 레퍼런스 코드로 미리 검증하는 경우)를 채점할 때 씀.
    `run_judge`는 이 함수에 `load_problem(problem_id)` 결과를 넘기는 얇은
    래퍼일 뿐이라, 둘의 채점 로직/응답 스펙은 항상 동일하다.
    """
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
    """격리된 컨테이너에서 학생 코드를 채점 하네스로 실행하고 결과를 반환한다.

    반환값은 {"status": "OK", "results": [...]} 또는
    {"status": "TIME_LIMIT"} / {"status": "RUNTIME_ERROR", "message": str} 중 하나.
    """
    payload = {"student_code": student_code, "test_cases": test_cases, "time_limit_sec": time_limit_sec}
    if check_type == "function_call":
        payload["function_name"] = problem["function_name"]

    container_timeout = _container_timeout(time_limit_sec, len(test_cases))
    harness_result = _run_container(HARNESS_BY_CHECK_TYPE[check_type], payload, container_timeout, mem_limit_mb)

    if harness_result.get("status") in ("TIME_LIMIT", "RUNTIME_ERROR"):
        return harness_result
    if "error" in harness_result:
        if harness_result["error"] == "timeout":
            return {"status": "TIME_LIMIT"}
        return {"status": "RUNTIME_ERROR", "message": harness_result["message"]}

    return {"status": "OK", "results": harness_result["results"]}


def capture_reference_outputs(
    reference_code: str,
    check_type: str,
    test_case_inputs: list,
    function_name: str | None = None,
    time_limit_sec: float = DEFAULT_TIME_LIMIT_SEC,
    memory_limit_mb: float = DEFAULT_MEM_LIMIT_MB,
) -> dict:
    """레퍼런스 정답 코드를 샌드박스에서 실행해 "실제로 나온 출력"을 캡처한다.

    문제 생성 파이프라인 전용. LLM이 문제를 만들 때 같이 내놓는 expected/
    expected_stdout은 LLM이 손으로 계산한 값이라 틀릴 수 있으므로 신뢰하지
    않는다 — 대신 아직 expected가 없는 입력값들(test_case_inputs, 예:
    stdout_match면 [{"stdin": "...", "category": "..."}])을 레퍼런스 코드로
    실제 실행시켜 나온 결과를 "진짜 expected"로 채택한다. run_judge와 달리
    정답 비교를 하지 않고 실행 결과만 그대로 반환한다 — 이걸 problems/*.json
    스키마의 expected/expected_stdout으로 채택할지는 호출자(agent)가 결정한다.

    학생 코드 채점과 동일한 Docker 격리(network_disabled/read_only/비루트 등)를
    그대로 적용한다 — 레퍼런스 코드도 LLM이 만든 것이라 무조건 신뢰하지 않는다.

    반환값: {"status": "OK", "outputs": [{"category": ..., "output": ...} 또는
    {"category": ..., "error": ...}, ...]} 또는 {"status": "SYNTAX_ERROR"|
    "TIME_LIMIT"|"RUNTIME_ERROR", "message": str}.
    """
    if check_type not in CAPTURE_HARNESS_BY_CHECK_TYPE:
        raise UnsupportedCheckTypeError(f"지원하지 않는 check_type입니다: {check_type}")

    # 채점 때와 동일하게, 컨테이너를 띄우기 전에 문법 오류부터 걸러낸다.
    try:
        compile(reference_code, "<reference_solution>", "exec")
    except SyntaxError as e:
        return {"status": "SYNTAX_ERROR", "message": str(e)}

    payload = {
        "student_code": reference_code,
        "test_case_inputs": test_case_inputs,
        "time_limit_sec": time_limit_sec,
    }
    if check_type == "function_call":
        payload["function_name"] = function_name

    container_timeout = _container_timeout(time_limit_sec, len(test_case_inputs))
    harness_result = _run_container(
        CAPTURE_HARNESS_BY_CHECK_TYPE[check_type], payload, container_timeout, memory_limit_mb
    )

    if harness_result.get("status") in ("TIME_LIMIT", "RUNTIME_ERROR"):
        return harness_result
    if "error" in harness_result:
        if harness_result["error"] == "timeout":
            return {"status": "TIME_LIMIT"}
        return {"status": "RUNTIME_ERROR", "message": harness_result["message"]}

    return {"status": "OK", "outputs": harness_result["outputs"]}


def _container_timeout(time_limit_sec: float, test_case_count: int) -> float:
    """컨테이너 전체 타임아웃(안전망)을 계산한다.

    time_limit_sec은 하네스가 테스트케이스마다 개별 적용하는 "테스트 1개당"
    제한. 컨테이너 전체 타임아웃은 그걸 어기지 않는 선에서, 하네스가 예상
    밖으로 멈춰버리는 경우를 잡는 안전망으로만 넉넉하게 잡는다.
    """
    return min(
        CONTAINER_TIMEOUT_CAP_SEC,
        time_limit_sec * max(test_case_count, 1) + CONTAINER_TIMEOUT_OVERHEAD_SEC,
    )


def _run_container(harness_path: str, payload: dict, container_timeout: float, mem_limit_mb: float) -> dict:
    """지정된 하네스 스크립트로 격리 컨테이너를 띄우고, 하네스가 stdout에 출력한
    JSON 결과를 그대로 반환한다. 채점 하네스(run_judge)와 캡처 하네스
    (capture_reference_outputs)가 이 실행/격리 로직을 공유한다.

    반환값: 하네스가 출력한 JSON dict (예: {"results": [...]} / {"outputs": [...]} /
    {"error": "timeout"}) 또는 {"status": "TIME_LIMIT"} / {"status": "RUNTIME_ERROR", "message": str}.
    """
    try:
        client = docker.from_env()
    except DockerException as e:
        return {"status": "RUNTIME_ERROR", "message": f"Docker 데몬에 연결할 수 없습니다: {e}"}

    mem_limit_str = f"{int(mem_limit_mb)}m"

    with tempfile.TemporaryDirectory() as tmp_dir:
        payload_path = Path(tmp_dir) / "payload.json"
        payload_path.write_text(json.dumps(payload), encoding="utf-8")

        try:
            container = client.containers.run(
                SANDBOX_IMAGE,
                entrypoint=["python", harness_path],
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
        return json.loads(logs.splitlines()[-1])
    except json.JSONDecodeError:
        return {"status": "RUNTIME_ERROR", "message": logs}
