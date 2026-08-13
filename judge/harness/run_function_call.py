"""컨테이너 내부에서 실행되는 채점 스크립트 (function_call).

호스트(judge_service.py)가 payload.json 경로를 커맨드 인자로 넘겨준다.

보안 설계 (중요): 학생 코드를 이 프로세스 안에서 직접 exec하지 않는다.
테스트케이스(+함수 존재 확인)마다 별도의 자식 프로세스를 띄워 그 안에서
exec + 함수 호출을 수행하고, 결과는 그 자식 프로세스의 stdout(부모가
캡처)으로만 받는다.

이렇게 하는 이유: 예전 버전은 학생 코드를 이 스크립트 자신의 프로세스에서
직접 exec했는데, 그러면 학생이 아래처럼 가짜 채점 결과를 stdout에 출력한
뒤 sys.exit()/os._exit()로 프로세스를 강제 종료시켜 이 스크립트의 "진짜"
최종 print()가 아예 실행되지 못하게 만들 수 있었다 (SystemExit은
`except Exception`으로 못 잡음). 그 결과 학생이 조작한 가짜 결과가 컨테이너의
마지막 출력이 되어 채점 결과로 둔갑하는 취약점이 있었다 (실제 재현 확인함).

자식 프로세스 방식에서는 학생 코드가 자기 자신의(자식) stdout/생명주기만
망가뜨릴 수 있고, 부모가 컨테이너의 최종 stdout에 쓰는 결과는 건드릴 수
없다. 자식에게는 테스트의 `input`(함수 인자)만 넘기고 `expected`(정답)는
절대 넘기지 않으므로, 자식 프로세스를 장악해도 정답을 알아낼 수 없다.
"""
import json
import subprocess
import sys

# 함수가 존재하고 호출 가능한지만 확인하는 자식 스크립트.
# ok=False일 때 detail에 구체적인 원인(예외 타입/메시지, 또는 함수 없음)을
# 실어 보낸다. 이 detail은 채점 결과(pass/fail)엔 전혀 영향을 주지 않고
# 진단 메시지로만 쓰이므로, 자식 프로세스가 뭘 보내든 안전하다.
_CHECK_RUNNER = """
import json, sys
student_code, function_name = sys.argv[1], sys.argv[2]
namespace = {}
try:
    exec(compile(student_code, "<student_code>", "exec"), namespace)
except Exception as e:
    print(json.dumps({"ok": False, "detail": f"{type(e).__name__}: {e}"}))
    sys.exit(0)
if callable(namespace.get(function_name)):
    print(json.dumps({"ok": True}))
else:
    print(json.dumps({"ok": False, "detail": f"함수 '{function_name}'을(를) 찾을 수 없습니다."}))
"""

# 함수를 실제로 한 번 호출해 리턴값을 stdout으로 보고하는 자식 스크립트.
# (expected 값은 넘기지 않는다 — 비교는 부모 쪽에서 한다)
_CALL_RUNNER = """
import json, sys
student_code, function_name, args_json = sys.argv[1], sys.argv[2], sys.argv[3]
namespace = {}
exec(compile(student_code, "<student_code>", "exec"), namespace)
actual = namespace[function_name](*json.loads(args_json))
print(json.dumps({"actual": actual}))
"""


def _run_child(script: str, args: list, timeout_sec: float):
    """자식 프로세스를 실행하고 stdout 마지막 줄을 JSON으로 파싱해 반환한다.
    비정상 종료/파싱 실패 시 None을 반환한다 (호출부에서 실패로 처리).
    자식이 timeout_sec을 넘기면 subprocess.TimeoutExpired를 그대로 던진다
    (호출부가 TIME_LIMIT으로 처리하도록)."""
    proc = subprocess.run(
        [sys.executable, "-c", script, *args],
        capture_output=True, text=True,
        timeout=timeout_sec,
    )
    if proc.returncode != 0:
        return None
    try:
        return json.loads(proc.stdout.strip().splitlines()[-1])
    except Exception:
        return None


def main(payload_path: str) -> None:
    with open(payload_path, "r", encoding="utf-8") as f:
        payload = json.load(f)

    student_code = payload["student_code"]
    function_name = payload["function_name"]
    test_cases = payload["test_cases"]
    time_limit_sec = payload["time_limit_sec"]  # 테스트케이스 1개당 제한시간

    try:
        check = _run_child(_CHECK_RUNNER, [student_code, function_name], time_limit_sec)
    except subprocess.TimeoutExpired:
        print(json.dumps({"error": "timeout"}))
        return

    if not check or not check.get("ok"):
        detail = (check or {}).get("detail", "코드 실행 중 알 수 없는 오류가 발생했습니다.")
        print(json.dumps({"error": "runtime", "message": detail}))
        return

    results = []
    for tc in test_cases:
        try:
            call_result = _run_child(
                _CALL_RUNNER, [student_code, function_name, json.dumps(tc["input"])], time_limit_sec
            )
        except subprocess.TimeoutExpired:
            # 테스트 하나가 제한시간을 넘기면 전체 제출을 TIME_LIMIT으로 즉시
            # 판정한다 (실제 저지들의 일반적인 TLE 판정과 동일 — 남은 테스트는 생략).
            print(json.dumps({"error": "timeout"}))
            return
        passed = call_result is not None and call_result.get("actual") == tc["expected"]
        results.append({"category": tc.get("category"), "passed": passed})

    print(json.dumps({"results": results}))


if __name__ == "__main__":
    main(sys.argv[1])
