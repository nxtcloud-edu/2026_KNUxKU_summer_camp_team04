"""stdout_match 채점 스크립트 (컨테이너 내부에서 실행).

학생 코드를 테스트케이스마다 독립된 파이썬 프로세스로 실행해 stdin을 넣고
stdout을 캡처한 뒤 expected_stdout과 비교한다. 한 프로세스에서 여러 테스트를
연달아 돌리면 전역 변수가 테스트 간에 새어나갈 수 있어, 케이스마다 새
서브프로세스로 격리 실행한다.

출력 규약은 run_function_call.py와 동일: stdout에 JSON 한 줄
({"results": [...]}). 컨테이너 자체가 이미 network_disabled/read_only/
pids_limit으로 격리돼 있으므로, 서브프로세스도 그 안에서만 실행된다.
"""
import json
import subprocess
import sys


def main(payload_path: str) -> None:
    with open(payload_path, "r", encoding="utf-8") as f:
        payload = json.load(f)

    student_code = payload["student_code"]
    test_cases = payload["test_cases"]

    results = []
    for tc in test_cases:
        try:
            proc = subprocess.run(
                [sys.executable, "-c", student_code],
                input=tc["stdin"],
                capture_output=True,
                text=True,
            )
            actual = proc.stdout.rstrip("\n")
            expected = tc["expected_stdout"].rstrip("\n")
            passed = proc.returncode == 0 and actual == expected
        except Exception:
            passed = False
        results.append({"category": tc.get("category"), "passed": passed})

    print(json.dumps({"results": results}))


if __name__ == "__main__":
    main(sys.argv[1])
