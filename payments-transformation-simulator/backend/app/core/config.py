"""Centralised configuration. Everything behaviourally interesting is env-configurable.

No secrets are hardcoded. Defaults are chosen so that a fresh clone runs locally
against SQLite with no setup at all.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_ROOT.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(PROJECT_ROOT / ".env", BACKEND_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- application -------------------------------------------------------
    APP_NAME: str = "Payments Transformation Simulator"
    APP_VERSION: str = "1.0.0"
    API_V1_PREFIX: str = "/api/v1"
    ENVIRONMENT: str = "local"
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "json"  # json | text

    # --- persistence -------------------------------------------------------
    # SQLite is the zero-setup local default; PostgreSQL is the production target.
    DATABASE_URL: str = f"sqlite+pysqlite:///{BACKEND_ROOT / 'data' / 'simulator.db'}"
    DB_ECHO: bool = False

    # --- demo / seeding ----------------------------------------------------
    DEMO_MODE: bool = True
    AUTO_SEED: bool = True
    SEED_PAYMENT_COUNT: int = 25

    # --- simulation timing -------------------------------------------------
    # "Accelerated" simulation: realistic thresholds are defined per scheme
    # (see app/schemes), but can be divided by this factor for demos.
    SIMULATION_SPEED_FACTOR: float = 5.0
    CLEARING_TIMEOUT_SECONDS: int = 25
    CLEARING_RESPONSE_DELAY_SECONDS: float = 1.5
    SETTLEMENT_DELAY_SECONDS: float = 1.0
    RECONCILIATION_DELAY_SECONDS: float = 1.5
    SCHEDULER_POLL_INTERVAL_SECONDS: float = 0.25
    SCHEDULER_ENABLED: bool = True

    # --- api hardening -----------------------------------------------------
    CORS_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173"
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_REQUESTS: int = 600
    RATE_LIMIT_WINDOW_SECONDS: int = 60
    MAX_PAGE_SIZE: int = 200

    # --- optional AI assist (never required) -------------------------------
    AI_ENABLED: bool = False
    AI_PROVIDER: str = "anthropic"
    AI_MODEL: str = "claude-sonnet-5-5"
    AI_API_KEY: str = Field(default="", repr=False)

    @field_validator("LOG_LEVEL")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.upper()

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def is_sqlite(self) -> bool:
        return self.DATABASE_URL.startswith("sqlite")

    def accelerate(self, seconds: float) -> float:
        """Apply the demo speed factor to a realistic duration."""
        factor = self.SIMULATION_SPEED_FACTOR if self.DEMO_MODE else 1.0
        return max(0.05, seconds / max(factor, 0.01))


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
