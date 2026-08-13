"""Judge 서비스를 감싸는 얇은 HTTP API (임시).

지금은 backend가 아직 없어서 프론트가 바로 붙을 수 있게 Judge가 임시로
API를 노출한다. 엔드포인트는 judge_service.py의 함수를 그대로 감싸기만
한다 — 실제 로직은 전부 judge_service.py에 있음. 나중에 backend가 생기면
이 레이어는 backend로 옮기거나, backend가 이 서비스를 호출하는 구조로
바뀔 수 있다 (함수 시그니처는 그대로 재사용 가능).

로컬 데모용이라 CORS를 전체 허용해뒀다. 실제로 배포한다면 반드시 프론트
도메인으로 제한할 것.

실행: uvicorn main:app --reload --port 8000   (judge/ 디렉터리에서)
"""
from __future__ import annotations

from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from judge_service import (
    ProblemNotFoundError,
    UnsupportedCheckTypeError,
    get_problem_detail,
    list_all_problems,
    run_judge,
)

app = FastAPI(title="CodeTrace Judge API (temporary)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # TODO: 배포 시 프론트 도메인으로 제한
    allow_methods=["*"],
    allow_headers=["*"],
)


class JudgeRequest(BaseModel):
    student_code: str
    problem_id: str
    mode: Literal["run", "submit"] = "run"


@app.get("/problems")
def get_problems() -> list:
    """문제 목록 (제목/개념만, 프론트 목록 페이지용)."""
    return list_all_problems()


@app.get("/problems/{problem_id}")
def get_problem(problem_id: str) -> dict:
    """문제 상세 (지문/코드 템플릿/공개 테스트케이스, hidden은 제외)."""
    try:
        return get_problem_detail(problem_id)
    except ProblemNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@app.post("/judge")
def judge(req: JudgeRequest) -> dict:
    """학생 코드 채점. mode="run"은 public만, "submit"은 public+hidden 전체."""
    try:
        return run_judge(req.student_code, req.problem_id, req.mode)
    except ProblemNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except UnsupportedCheckTypeError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
