from __future__ import annotations

from pydantic import BaseModel, Field

from app.enums import SessionStatus
from app.schemas_common import UtcDatetime


class SessionCreate(BaseModel):
    problem_id: str = Field(max_length=64)
    user_id: str = Field(default="demo-user", max_length=64)


class SessionRead(BaseModel):
    session_id: str
    user_id: str
    problem_id: str
    status: SessionStatus
    started_at: UtcDatetime
    finished_at: UtcDatetime | None
    last_code_version: int
    last_event_seq: int
    # 생성 응답뿐 아니라 조회 응답에도 넣는다: 왕복 한 번을 없애고
    # frontend_plan §17의 새로고침 복구 요구사항을 그대로 만족시킨다.
    current_code: str
    current_code_version: int
