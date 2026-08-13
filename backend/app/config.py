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


DEFAULT_MONITOR_CONFIG = MonitorConfig()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    app_env: str = "dev"
    log_level: str = "INFO"
    sql_echo: bool = False

    database_url: str = "sqlite:///./codetrace.db"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    problems_dir: str = "app/problems/data"

    # Seam
    judge_backend: str = "none"  # none | docker
    judge_path: str = "../judge"
    agent_backend: str = "none"  # none | llm

    # Monitor
    monitor_no_progress_seconds: int = 90
    monitor_same_result_threshold: int = 3
    monitor_same_region_threshold: int = 2
    monitor_consecutive_error_threshold: int = 3
    monitor_cooldown_seconds: int = 30
    monitor_large_change_ratio: float = 0.5
    monitor_large_change_min_lines: int = 5
    monitor_large_change_window_seconds: int = 60
    monitor_recent_score_window: int = 5

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
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
