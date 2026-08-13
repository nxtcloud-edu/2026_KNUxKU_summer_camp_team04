"""레퍼런스 코드의 실제 출력을 캡처하는 스크립트 (컨테이너 내부에서 실행).

run_stdout_match.py와 격리 방식(테스트케이스마다 독립 서브프로세스)은 동일하지만,
expected_stdout과 비교하지 않고 실제로 나온 stdout을 그대로 반환한다. 문제 생성
파이프라인이 레퍼런스 정답 코드의 실제 출력을 캡처해 expected_stdout을 확정할 때
쓴다 (학생 코드를 채점하는 run_stdout_match.py와는 별도 경로 — 여기서 실행하는
코드는 학생 제출이 아니라 신뢰도가 더 높은 레퍼런스 코드지만, 그래도 컨테이너
격리는 동일하게 적용한다 — LLM이 만든 코드도 무조건 믿지는 않는다는 원칙).
"""
import json
import subprocess
import sys


def main(payload_path: str) -> None:
    with open(payload_path, "r", encoding="utf-8") as f:
        payload = json.load(f)

    reference_code = payload["student_code"]
    test_case_inputs = payload["test_case_inputs"]
    time_limit_sec = payload["time_limit_sec"]  # 테스트케이스 1개당 제한시간

    outputs = []
    for tc in test_case_inputs:
        try:
            proc = subprocess.run(
                [sys.executable, "-c", reference_code],
                input=tc["stdin"],
                capture_output=True,
                text=True,
                timeout=time_limit_sec,
            )
        except subprocess.TimeoutExpired:
            # run_stdout_match.py와 동일하게, 하나라도 시간 초과면 전체를 중단한다
            # (실제 저지들의 TLE 판정과 동일 — 남은 테스트는 생략).
            print(json.dumps({"error": "timeout"}))
            return

        if proc.returncode != 0:
            outputs.append({
                "category": tc.get("category"),
                "error": proc.stderr.strip()[-500:] or "런타임 오류",
            })
        else:
            outputs.append({"category": tc.get("category"), "output": proc.stdout.rstrip("\n")})

    print(json.dumps({"outputs": outputs}))


if __name__ == "__main__":
    main(sys.argv[1])
