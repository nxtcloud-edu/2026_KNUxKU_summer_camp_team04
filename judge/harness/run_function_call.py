"""컨테이너 내부에서 실행되는 채점 스크립트.

호스트(judge_service.py)가 이 이미지를 컨테이너로 띄울 때 payload.json 경로를
커맨드 인자로 넘겨준다. 이 스크립트는:
  1. 학생 코드를 exec()해서 함수를 정의시키고
  2. 지정된 function_name을 테스트케이스별로 호출해 expected와 비교하고
  3. 결과를 JSON 한 줄로 stdout에 출력한다 (호스트는 stdout의 마지막 줄만 파싱함)

이 스크립트 자체는 신뢰된 코드지만, exec되는 student_code는 신뢰할 수 없으므로
호스트 쪽에서 network_disabled/mem_limit/pids_limit/read_only 등으로 컨테이너를
격리시킨 뒤 이 스크립트를 실행해야 한다.
"""
import json
import sys


def main(payload_path: str) -> None:
    with open(payload_path, "r", encoding="utf-8") as f:
        payload = json.load(f)

    student_code = payload["student_code"]
    function_name = payload["function_name"]
    test_cases = payload["test_cases"]

    namespace: dict = {}
    try:
        exec(compile(student_code, "<student_code>", "exec"), namespace)
    except Exception as e:
        print(json.dumps({"error": "runtime", "message": f"{type(e).__name__}: {e}"}))
        return

    func = namespace.get(function_name)
    if func is None or not callable(func):
        print(json.dumps({
            "error": "runtime",
            "message": f"함수 '{function_name}'을 찾을 수 없습니다.",
        }))
        return

    results = []
    for tc in test_cases:
        try:
            actual = func(*tc["input"])
            passed = actual == tc["expected"]
        except Exception:
            passed = False
        results.append({"category": tc.get("category"), "passed": passed})

    print(json.dumps({"results": results}))


if __name__ == "__main__":
    main(sys.argv[1])
