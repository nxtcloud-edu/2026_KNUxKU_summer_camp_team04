from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.agent.router import router as agent_router
from app.config import get_settings
from app.db import init_db
from app.errors import register_error_handlers
from app.judge.router import router as judge_router
from app.problems.router import router as problems_router
from app.sessions.router import router as sessions_router
from app.trace.router import router as trace_router


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)

    app = FastAPI(
        title="CodeTrace Backend",
        version="0.1.0",
        description=(
            "Coding Trace 수집 파이프라인. 학생의 편집/실행 이벤트를 저장하고 "
            "Process Feature와 Monitor 판단으로 변환한다. JSON은 전부 snake_case."
        ),
        lifespan=lifespan,
    )

    # 1단계에 넣는다. 없으면 모든 프론트 호출이 불투명한 브라우저 에러로 실패한다.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_error_handlers(app)

    app.include_router(problems_router)
    app.include_router(sessions_router)
    app.include_router(trace_router)
    app.include_router(judge_router)
    app.include_router(agent_router)

    @app.get("/health", tags=["meta"])
    def health() -> dict[str, str]:
        return {
            "status": "ok",
            "judge_backend": settings.judge_backend,
            "agent_backend": settings.agent_backend,
        }

    return app


app = create_app()
