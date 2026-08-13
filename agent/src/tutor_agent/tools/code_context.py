"""에이전트가 쓸 수 있는 Strands 도구 예시.

실제로는 코드 실행 결과, 테스트 통과 여부, 커서 위치 등 backend/frontend가 가진
정보를 읽어오는 도구가 필요하다. 지금은 파이프라인 배선을 보여주기 위한
자리표시자(placeholder) 도구 하나만 둔다.
"""

from __future__ import annotations

from strands import tool


@tool
def summarize_run_history(run_history: list[str]) -> str:
    """최근 실행/제출 로그 목록을 사람이 읽기 쉬운 한 줄 요약으로 변환한다.

    Args:
        run_history: 최근 실행 결과 로그 문자열 리스트 (예: "3/5 tests passed").
    """
    if not run_history:
        return "아직 실행 기록이 없습니다."
    return " → ".join(run_history[-5:])
