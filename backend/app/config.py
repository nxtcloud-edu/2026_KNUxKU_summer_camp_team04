"""설정.

MonitorConfig는 Settings에서 **값으로** 뽑아 monitor/features 함수에 인자로 넘긴다.
전역을 직접 읽지 않는 이유: 그러면 테스트가 환경변수 순서에 의존하게 된다.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class MonitorConfig:
    """Monitor / Feature extractor의 임계값 묶음."""

    no_progress_seconds: int = 90
    same_result_threshold: int = 3
    same_region_threshold: int = 2
    consecutive_error_threshold: int = 3
    cooldown_seconds: int = 30
    large_change_ratio: float = 0.5
    large_change_min_lines: int = 5
    large_change_window_seconds: int = 60
    recent_score_window: int = 5

    # --- 편집만으로 발화하는 규칙(R7b/R7c)의 임계값 ---
    # 위 임계값들이 전부 채점 결과(TEST_RESULT)를 요구하기 때문에, 학생이 실행/제출을
    # 한 번도 누르지 않으면 R0(도움 요청) 말고는 발화할 수 있는 규칙이 없었다.
    # 아래 둘은 편집 이벤트만으로 판정한다.
    #
    # no_progress_seconds(90초)와 다른 시계를 쓴다: 그건 "마지막 채점 개선 이후"라
    # 학생이 활발히 타이핑하는 중에도 계속 증가한다. 이쪽은 "마지막 편집 이후"다.
    idle_edit_seconds: int = 45
    # 같은 영역을 이만큼 반복 수정하면 churn으로 본다.
    edit_churn_threshold: int = 3
    # 붙여넣기 직후 이만큼 손을 떼고 있으면 "이해도 확인" 분기로 보낸다.
    # 신호 하나(붙여넣기)만으로 개입하지 않기 위한 두 번째 조건이다.
    #
    # 이 값이 곧 학생이 체감하는 지연의 절반 이상이다(실측: 붙여넣기 -> 힌트까지
    # 서버가 쓰는 13.7초 중 8초가 여기, 나머지 5.6초가 LLM). 붙여넣고 5초를 그대로
    # 쳐다보고 있으면 "직접 친 게 아니다"라는 판단에 충분하다.
    paste_settle_seconds: int = 5


DEFAULT_MONITOR_CONFIG = MonitorConfig()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    app_env: str = "dev"
    log_level: str = "INFO"
    sql_echo: bool = False

    database_url: str = "sqlite:///./codetrace.db"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:5174,http://127.0.0.1:5174"

    problems_dir: str = "../judge/problems"

    # Seam
    judge_backend: str = "none"  # none | docker
    judge_path: str = "../judge"
    agent_backend: str = "none"  # none | llm

    # 인증. jwt_secret은 **운영에서 반드시 바꾼다.**
    # 기본값을 그대로 쓰면 누구나 아무 사용자의 토큰을 발급할 수 있다.
    # HS256은 32바이트 이상을 권장한다(RFC 7518 §3.2). 기본값도 그 길이를 맞춘다.
    jwt_secret: str = "dev-only-change-me-in-production-0123456789abcdef"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 12  # 데모 편의상 길게

    # 도토리 지급/차감 정책 (문서 §6의 권장 MVP)
    # judge 문제 26개에 difficulty가 전부 없어서 지금은 모두 BEGINNER=10으로 수렴한다.
    # BE1이 difficulty를 채우면 아래 매핑이 그대로 동작한다.
    acorn_reward_beginner: int = 10
    acorn_reward_intermediate: int = 15
    acorn_reward_advanced: int = 20
    acorn_reward_trace_completed: int = 3
    acorn_cost_nickname: int = 5
    acorn_cost_avatar: int = 10

    # 닉네임 정책
    nickname_min_length: int = 2
    nickname_max_length: int = 16
    nickname_banned_words: str = "admin,관리자,운영자,operator,root,system"

    @property
    def banned_nickname_list(self) -> list[str]:
        return [w.strip().lower() for w in self.nickname_banned_words.split(",") if w.strip()]

    def acorn_reward_for(self, difficulty: str) -> int:
        return {
            "BEGINNER": self.acorn_reward_beginner,
            "INTERMEDIATE": self.acorn_reward_intermediate,
            "ADVANCED": self.acorn_reward_advanced,
        }.get((difficulty or "").upper(), self.acorn_reward_beginner)

    # Monitor.
    # **기본값을 여기 다시 적지 않는다.** MonitorConfig의 필드 기본값을 그대로
    # 끌어온다 -- 두 곳에 숫자를 쓰면 조용히 어긋난다(실제로 paste_settle을
    # MonitorConfig에서만 5로 낮췄더니 여기 10이 이겨서 아무 변화가 없었다).
    monitor_no_progress_seconds: int = DEFAULT_MONITOR_CONFIG.no_progress_seconds
    monitor_same_result_threshold: int = DEFAULT_MONITOR_CONFIG.same_result_threshold
    monitor_same_region_threshold: int = DEFAULT_MONITOR_CONFIG.same_region_threshold
    monitor_consecutive_error_threshold: int = DEFAULT_MONITOR_CONFIG.consecutive_error_threshold
    monitor_cooldown_seconds: int = DEFAULT_MONITOR_CONFIG.cooldown_seconds
    monitor_large_change_ratio: float = DEFAULT_MONITOR_CONFIG.large_change_ratio
    monitor_large_change_min_lines: int = DEFAULT_MONITOR_CONFIG.large_change_min_lines
    monitor_large_change_window_seconds: int = DEFAULT_MONITOR_CONFIG.large_change_window_seconds
    monitor_recent_score_window: int = DEFAULT_MONITOR_CONFIG.recent_score_window
    monitor_idle_edit_seconds: int = DEFAULT_MONITOR_CONFIG.idle_edit_seconds
    monitor_edit_churn_threshold: int = DEFAULT_MONITOR_CONFIG.edit_churn_threshold
    monitor_paste_settle_seconds: int = DEFAULT_MONITOR_CONFIG.paste_settle_seconds

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def problems_path(self) -> Path:
        p = Path(self.problems_dir)
        return p if p.is_absolute() else (BACKEND_ROOT / p)

    @property
    def monitor(self) -> MonitorConfig:
        return MonitorConfig(
            no_progress_seconds=self.monitor_no_progress_seconds,
            same_result_threshold=self.monitor_same_result_threshold,
            same_region_threshold=self.monitor_same_region_threshold,
            consecutive_error_threshold=self.monitor_consecutive_error_threshold,
            cooldown_seconds=self.monitor_cooldown_seconds,
            large_change_ratio=self.monitor_large_change_ratio,
            large_change_min_lines=self.monitor_large_change_min_lines,
            large_change_window_seconds=self.monitor_large_change_window_seconds,
            recent_score_window=self.monitor_recent_score_window,
            idle_edit_seconds=self.monitor_idle_edit_seconds,
            edit_churn_threshold=self.monitor_edit_churn_threshold,
            paste_settle_seconds=self.monitor_paste_settle_seconds,
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
