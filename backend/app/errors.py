"""에러 봉투.

우리가 던지는 에러:
    {"detail": {"code": "SESSION_NOT_FOUND", "message": "...", "context": {...}}}

FastAPI의 422 validation 에러는 네이티브 배열 형태를 유지한다.
둘 다 `detail` 아래에 있으므로 frontend_plan §15의 ApiError { status, detail }가
두 경우를 모두 처리한다.
"""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    status_code: int = 400
    code: str = "APP_ERROR"

    def __init__(self, message: str, **context: Any) -> None:
        super().__init__(message)
        self.message = message
        self.context = context

    def to_response(self) -> JSONResponse:
        return JSONResponse(
            status_code=self.status_code,
            content={
                "detail": {
                    "code": self.code,
                    "message": self.message,
                    "context": self.context,
                }
            },
        )


class SessionNotFound(AppError):
    status_code = 404
    code = "SESSION_NOT_FOUND"

    def __init__(self, session_id: str) -> None:
        super().__init__("세션을 찾을 수 없습니다.", session_id=session_id)


# --------------------------------------------------------------------- 인증


class InvalidCredentials(AppError):
    """이메일이 없든 비밀번호가 틀렸든 **같은 에러**를 던진다.

    구분해서 알려주면 "이 이메일은 가입되어 있다"를 확인시켜 주는 계정 열거
    취약점이 된다.
    """

    status_code = 401
    code = "INVALID_CREDENTIALS"

    def __init__(self) -> None:
        super().__init__("이메일 또는 비밀번호가 올바르지 않습니다.")


class NotAuthenticated(AppError):
    status_code = 401
    code = "NOT_AUTHENTICATED"

    def __init__(self, message: str = "로그인이 필요합니다.") -> None:
        super().__init__(message)


class EmailAlreadyRegistered(AppError):
    status_code = 409
    code = "EMAIL_ALREADY_REGISTERED"

    def __init__(self) -> None:
        super().__init__("이미 가입된 이메일입니다.")


class NicknameTaken(AppError):
    status_code = 409
    code = "NICKNAME_TAKEN"

    def __init__(self, nickname: str) -> None:
        super().__init__("이미 사용 중인 닉네임입니다.", nickname=nickname)


class InvalidNickname(AppError):
    status_code = 422
    code = "INVALID_NICKNAME"

    def __init__(self, message: str) -> None:
        super().__init__(message)


class UserNotFound(AppError):
    status_code = 404
    code = "USER_NOT_FOUND"

    def __init__(self, user_id: str) -> None:
        super().__init__("사용자를 찾을 수 없습니다.", user_id=user_id)


class InsufficientAcorns(AppError):
    status_code = 402
    code = "INSUFFICIENT_ACORNS"

    def __init__(self, *, required: int, balance: int) -> None:
        super().__init__(
            f"도토리가 부족합니다. {required}개가 필요하지만 {balance}개를 가지고 있습니다.",
            required=required,
            balance=balance,
        )


class ProblemNotFound(AppError):
    status_code = 404
    code = "PROBLEM_NOT_FOUND"

    def __init__(self, problem_id: str) -> None:
        super().__init__("문제를 찾을 수 없습니다.", problem_id=problem_id)


class SnapshotNotFound(AppError):
    status_code = 404
    code = "SNAPSHOT_NOT_FOUND"

    def __init__(self, session_id: str, version: int) -> None:
        super().__init__(
            "코드 스냅샷을 찾을 수 없습니다.", session_id=session_id, version=version
        )


class ServerOnlyEvent(AppError):
    status_code = 422
    code = "SERVER_ONLY_EVENT"

    def __init__(self, event_type: str) -> None:
        super().__init__(
            "서버만 생성할 수 있는 이벤트 타입입니다.", event_type=event_type
        )


class InvalidCodeVersion(AppError):
    status_code = 422
    code = "INVALID_CODE_VERSION"

    def __init__(self, requested: int, latest: int) -> None:
        super().__init__(
            "존재하지 않는 code_version입니다.", requested=requested, latest=latest
        )


class MissingSnapshotCode(AppError):
    status_code = 422
    code = "MISSING_SNAPSHOT_CODE"

    def __init__(self) -> None:
        super().__init__("CODE_SNAPSHOT 이벤트에는 payload.code가 필요합니다.")


class JudgeUnavailable(AppError):
    status_code = 503
    code = "JUDGE_UNAVAILABLE"

    def __init__(self, message: str) -> None:
        super().__init__(message)


class AgentUnavailable(AppError):
    status_code = 503
    code = "AGENT_UNAVAILABLE"

    def __init__(self, message: str) -> None:
        super().__init__(message)


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _handle_app_error(_request: Request, exc: AppError) -> JSONResponse:
        return exc.to_response()
