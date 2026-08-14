"""학생에게 말을 거는 에이전트들이 쓰는 **압축된** 프롬프트 컨텍스트.

왜 `ctx.model_dump_json()`을 그대로 쓰지 않는가
-----------------------------------------------
`state_agent` / `guided_action_agent`는 판단을 해야 하니 `SessionContext` 전체를
직렬화해서 넣는다 (`backend_signals` 안의 `features`까지 통째로). 그 안에는
이런 값들이 있다:

    "seconds_without_progress": 1879,
    "same_region_edit_count": 4,
    "hint_count": 6,
    "evidence": ["동일 결과 0/5 x3", "24분간 편집 없음"]

**학생에게 말을 거는 에이전트에 이걸 그대로 넣으면 그대로 튀어나온다.** 실제로
"31분 넘게 완전히 막혀 있습니다 ... 힌트를 6회 요청했지만 진전이 없습니다"
같은 문장이 학생 화면에 떴다. 학생에게 필요한 정보(문제가 뭔지, 지금 코드가
어떤지, 어디서 틀렸는지)와 시스템이 개입을 결정하기 위해 필요한 정보(정체
시간, churn 횟수, 힌트 요청 횟수)는 다르다.

그래서 작문/평가 단계에는 이 모듈이 만든 압축 컨텍스트만 넣는다:

* 문제 정보 (제목, 한 줄 설명, 함수 이름)
* 학생의 현재 코드
* 마지막 에러 / 최근 채점 결과 한 줄

**의도적으로 넣지 않는 것**: 유휴 시간, churn/힌트 횟수, Monitor evidence,
그리고 `StudentState.state_summary`. state_summary는 "학생은 ~하지 못한 채
막혀 있습니다" 같은 3인칭 분석문이라, 프롬프트에 있으면 모델이 그 톤을 그대로
복사한다. 그 분석에서 뽑아낸 *지도용 결론*은 이미
`GuidancePlan.focus`/`talking_points`로 전달되므로 정보가 유실되지도 않는다.
"""

from __future__ import annotations

from .schemas import SessionContext

#: 프롬프트에 싣는 코드 최대 길이. 초과분은 잘라낸다 (토큰 폭주 방지).
MAX_CODE_CHARS = 4000


def _as_dict(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def problem_brief(ctx: SessionContext) -> str:
    """문제 정보를 사람이 읽는 형태로 몇 줄. backend가 없으면 problem_id만 나온다."""
    problem = _as_dict(ctx.backend_signals.get("problem"))
    lines: list[str] = []
    title = str(problem.get("title", "") or "")
    summary = str(problem.get("description_summary", "") or "")
    function_name = str(problem.get("function_name", "") or "")
    concepts = problem.get("concepts")

    lines.append(f"문제 ID: {ctx.problem_id or '(없음)'}")
    if title:
        lines.append(f"제목: {title}")
    if summary:
        lines.append(f"설명: {summary}")
    if function_name:
        lines.append(f"작성해야 할 함수: {function_name}")
    if isinstance(concepts, (list, tuple)) and concepts:
        lines.append(f"개념: {', '.join(str(c) for c in concepts)}")
    return "\n".join(lines)


def code_brief(ctx: SessionContext) -> str:
    code = ctx.code.strip()
    if not code:
        return "(학생이 아직 아무 코드도 작성하지 않았습니다)"
    if len(code) > MAX_CODE_CHARS:
        code = code[:MAX_CODE_CHARS] + "\n... (이하 생략)"
    return code


def result_brief(ctx: SessionContext) -> str:
    """마지막 에러와 최근 채점 결과. 없으면 빈 문자열."""
    lines: list[str] = []
    if ctx.last_error:
        lines.append(f"마지막 에러: {ctx.last_error}")

    judge = _as_dict(ctx.backend_signals.get("judge_result"))
    if judge:
        status = str(judge.get("status", "") or "")
        passed, total = judge.get("passed"), judge.get("total")
        if status:
            line = f"최근 채점: {status}"
            if isinstance(passed, int) and isinstance(total, int) and total:
                line += f" ({passed}/{total} 통과)"
            lines.append(line)
        categories = judge.get("failed_categories")
        if isinstance(categories, (list, tuple)) and categories:
            lines.append(f"실패한 테스트 유형: {', '.join(str(c) for c in categories)}")
    elif ctx.run_history:
        lines.append(f"최근 실행 결과: {ctx.run_history[-1]}")

    return "\n".join(lines)


def student_situation(ctx: SessionContext) -> str:
    """작문/평가 에이전트에 넣을 압축 컨텍스트 한 덩어리.

    모듈 docstring에 적은 대로, 개입 판단용 텔레메트리(유휴 시간, churn 횟수,
    힌트 요청 횟수, Monitor evidence)와 3인칭 상태 요약은 **일부러 빠져 있다.**
    """
    blocks = [f"[문제]\n{problem_brief(ctx)}", f"[학생의 현재 코드]\n```python\n{code_brief(ctx)}\n```"]
    results = result_brief(ctx)
    if results:
        blocks.append(f"[실행/채점 상황]\n{results}")
    return "\n\n".join(blocks)
