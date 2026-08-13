"""레퍼런스 코드의 함수 리턴값을 캡처하는 스크립트 (컨테이너 내부에서 실행).

run_function_call.py의 자식 프로세스 격리(_CHECK_RUNNER/_CALL_RUNNER)를 그대로
재사용한다 — 둘 다 "정답과 비교하지 않고 실제 리턴값만 stdout으로 보고"하는
구조라 애초에 expected가 필요 없었다. 이 스크립트는 그 결과를 비교 없이 그대로
넘기기만 한다. 문제 생성 파이프라인이 레퍼런스 정답 함수의 실제 리턴값을 캡처해
expected를 확정할 때 쓴다 (학생 코드를 채점하는 run_function_call.py와는 별도 경로).
"""
import json
import subprocess
import sys

from run_function_call import _CALL_RUNNER, _CHECK_RUNNER, _run_child


def main(payload_path: str) -> None:
    with open(payload_path, "r", encoding="utf-8") as f:
        payload = json.load(f)

    reference_code = payload["student_code"]
    function_name = payload["function_name"]
    test_case_inputs = payload["test_case_inputs"]
    time_limit_sec = payload["time_limit_sec"]  # 테스트케이스 1개당 제한시간

    try:
        check = _run_child(_CHECK_RUNNER, [reference_code, function_name], time_limit_sec)
    except subprocess.TimeoutExpired:
        print(json.dumps({"error": "timeout"}))
        return

    if not check or not check.get("ok"):
        detail = (check or {}).get("detail", "코드 실행 중 알 수 없는 오류가 발생했습니다.")
        print(json.dumps({"error": "runtime", "message": detail}))
        return

    outputs = []
    for tc in test_case_inputs:
        try:
            call_result = _run_child(
                _CALL_RUNNER, [reference_code, function_name, json.dumps(tc["input"])], time_limit_sec
            )
        except subprocess.TimeoutExpired:
            # run_function_call.py와 동일하게, 하나라도 시간 초과면 전체를 중단한다.
            print(json.dumps({"error": "timeout"}))
            return

        if call_result is None:
            outputs.append({
                "category": tc.get("category"),
                "error": "레퍼런스 코드 실행 중 오류가 발생했습니다.",
            })
        else:
            outputs.append({"category": tc.get("category"), "output": call_result["actual"]})

    print(json.dumps({"outputs": outputs}))


if __name__ == "__main__":
    main(sys.argv[1])
