"""인프라 장애는 INTERNAL_ERROR 다 (학생 코드 잘못이 아니다).

Docker 가 실행 중이어야 하고, 샌드박스 이미지가 빌드돼 있어야 한다:
    docker build -t judge-sandbox .   (judge/ 디렉터리에서)

원래 버그
--------
데몬 연결 실패 · 컨테이너 실행 실패 · 무출력 · 로그 JSON 파싱 실패를 전부
`RUNTIME_ERROR` 로 보고했다. backend 는 그걸 학생 에러로 집계하므로
**도커가 죽어 있으면 학생이 Run 을 세 번 누르는 것만으로 "반복 실패" 판정**이
나고 agent 가 개입했다.

경계선
------
  하네스가 실행됐고 결과를 보고했다  -> 학생 책임 (RUNTIME_ERROR / TIME_LIMIT)
  하네스를 실행하지 못했거나 출력이 깨졌다 -> 우리 책임 (INTERNAL_ERROR)

이 구분이 성립하는 근거: 하네스는 `status` 키를 절대 쓰지 않고
{"results"|"outputs": ...} 또는 {"error": ...} 만 낸다. 그래서 호스트가 만든
status 의 존재 자체가 "호스트 측에서 뭔가 잘못됐다"의 판별자가 된다.
"""
from docker.errors import DockerException

import judge_service
from judge_service import (
    HOST_OUTCOME_STATUSES,
    capture_reference_outputs,
    load_problem,
    run_judge,
    run_judge_for_problem,
)

PROBLEM_ID = "func_sum_list"
GOOD_CODE = "def sum_list(arr):\n    return sum(arr)\n"


# --------------------------------------------------------------- 계약


def test_runtime_error_is_not_a_host_outcome():
    """RUNTIME_ERROR 가 HOST_OUTCOME_STATUSES 에 없는 것이 의도다.

    학생 코드의 런타임 예외는 하네스가 {"error": "runtime"} 으로 보고하고
    _run_in_sandbox 가 번역한다. 호스트가 직접 만들지 않는다.
    """
    assert "INTERNAL_ERROR" in HOST_OUTCOME_STATUSES
    assert "TIME_LIMIT" in HOST_OUTCOME_STATUSES
    assert "RUNTIME_ERROR" not in HOST_OUTCOME_STATUSES


# --------------------------------------------------------------- 4대 장애 지점


def test_docker_daemon_unreachable(monkeypatch):
    """장애 ①: 데몬에 붙지 못한다. 가장 흔한 케이스(도커 데스크톱이 꺼져 있음)."""

    def boom():
        raise DockerException("Cannot connect to the Docker daemon")

    monkeypatch.setattr(judge_service.docker, "from_env", boom)

    result = run_judge(GOOD_CODE, PROBLEM_ID, mode="run")
    assert result["status"] == "INTERNAL_ERROR"
    assert result["passed"] == 0
    assert "Docker 데몬" in result["message"]


def test_sandbox_image_unusable(monkeypatch):
    """장애 ②: 컨테이너를 띄울 수 없다 (이미지 미빌드/이름 오류).

    대문자가 든 이름은 도커가 즉시 거부하므로 네트워크 없이 재현된다.
    """
    monkeypatch.setattr(judge_service, "SANDBOX_IMAGE", "INVALID_UPPERCASE_NAME")

    result = run_judge(GOOD_CODE, PROBLEM_ID, mode="run")
    assert result["status"] == "INTERNAL_ERROR"
    assert result["passed"] == 0


def test_container_produces_no_output(monkeypatch):
    """장애 ③: 컨테이너가 아무것도 출력하지 않는다.

    하네스는 항상 JSON 한 줄을 낸다. 비어 있으면 하네스가 시작조차 못 한 것이다
    (이미지 손상, OOM kill 등). /dev/null 을 스크립트로 실행해 재현한다.
    """
    monkeypatch.setitem(judge_service.HARNESS_BY_CHECK_TYPE, "function_call", "/dev/null")

    result = run_judge(GOOD_CODE, PROBLEM_ID, mode="run")
    assert result["status"] == "INTERNAL_ERROR"
    assert "출력이 없습니다" in result["message"]


def test_container_output_is_not_json(monkeypatch):
    """장애 ④: 출력이 JSON 이 아니다 = 하네스 자체의 크래시.

    **이 테스트가 실제로 있었던 사고를 잡는다.** capture 하네스 2개가 추가된 뒤
    이미지를 다시 빌드하지 않으면 컨테이너가 "No such file" 을 뱉는데, 예전에는
    그게 RUNTIME_ERROR(학생 코드 잘못)로 보고됐다.
    """
    monkeypatch.setitem(
        judge_service.HARNESS_BY_CHECK_TYPE, "function_call", "/harness/does_not_exist.py"
    )

    result = run_judge(GOOD_CODE, PROBLEM_ID, mode="run")
    assert result["status"] == "INTERNAL_ERROR"
    assert "No such file" in result["message"]


# --------------------------------------------------------------- 회귀 가드


def test_student_runtime_error_is_still_runtime_error():
    """학생 코드가 원인이면 그대로 RUNTIME_ERROR 다. 경계선이 흐려지면 안 된다."""
    result = run_judge("def not_sum_list(arr):\n    return sum(arr)\n", PROBLEM_ID, mode="run")
    assert result["status"] == "RUNTIME_ERROR"


def test_student_timeout_is_still_time_limit():
    result = run_judge(
        "def sum_list(arr):\n    while True:\n        pass\n", PROBLEM_ID, mode="run"
    )
    assert result["status"] == "TIME_LIMIT"


def test_healthy_judge_is_unaffected():
    """정상 경로가 그대로여야 한다."""
    result = run_judge(GOOD_CODE, PROBLEM_ID, mode="submit")
    assert result["status"] == "ACCEPTED"
    assert result["passed"] == result["total"]


def test_run_judge_for_problem_reports_total_on_internal_error(monkeypatch):
    """INTERNAL_ERROR 여도 total 은 실제 테스트 개수여야 한다.

    프론트가 "0/0 통과"를 그리면 학생이 문제가 비어 있다고 오해한다.
    """
    monkeypatch.setattr(judge_service.docker, "from_env", lambda: (_ for _ in ()).throw(DockerException("down")))

    problem = load_problem(PROBLEM_ID)
    expected_total = len(problem["public_test_cases"])
    result = run_judge_for_problem(GOOD_CODE, problem, mode="run")

    assert result["status"] == "INTERNAL_ERROR"
    assert result["total"] == expected_total
    assert expected_total > 0


# --------------------------------------------------------------- 문제 생성 경로


def test_capture_reference_outputs_reports_internal_error(monkeypatch):
    """문제 생성 파이프라인도 같은 구분을 받아야 한다.

    레퍼런스 코드가 틀린 것(RUNTIME_ERROR)과 채점기가 고장난 것(INTERNAL_ERROR)을
    구분하지 못하면, agent 가 멀쩡한 후보 문제를 "레퍼런스가 틀렸다"며 버린다.
    """
    monkeypatch.setattr(judge_service.docker, "from_env", lambda: (_ for _ in ()).throw(DockerException("down")))

    result = capture_reference_outputs(
        reference_code=GOOD_CODE,
        check_type="function_call",
        test_case_inputs=[{"input": [[1, 2, 3]], "category": "basic"}],
        function_name="sum_list",
    )
    assert result["status"] == "INTERNAL_ERROR"
