"""Application settings, loaded from the environment (12-factor).

Security defaults: DEBUG is off, CORS origins are explicit, and outside
APP_ENV=development a wildcard CORS origin or DEBUG=True stops startup.
BigQuery + Knowledge Catalog serve as the sole data & context layer.
"""

from pathlib import Path
from typing import Self

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

MIN_SECRET_CHARS = 32
DEFAULT_AGENTS_DIR = str((Path(__file__).resolve().parents[3] / "agent").resolve())


class Settings(BaseSettings):
    """Typed environment settings for `knowledgestudio-devfest2026`."""

    APP_NAME: str = "knowledgestudio-devfest2026"
    APP_ENV: str = "development"
    DEBUG: bool = False
    PORT: int = 8080

    GCP_PROJECT_ID: str = ""
    GCP_REGION: str = "us-central1"
    BQ_DATASET_ID: str = "cymbal_retail_my"

    CORS_ORIGINS: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:3000",
            "http://localhost:8080",
            "http://localhost:8081",
            "http://127.0.0.1:8080",
            "http://127.0.0.1:8081",
        ]
    )

    JWT_SECRET_KEY: SecretStr | None = None
    AGENT_API_KEY: SecretStr | None = None
    AGENT_TIMEOUT_S: float = Field(default=120.0, gt=0, le=600)
    ENABLE_ADK_WEB_UI: bool = False
    ADK_AGENTS_DIR: str = DEFAULT_AGENTS_DIR

    model_config = SettingsConfigDict(
        env_file=(".env.local", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def is_development(self) -> bool:
        """Return True when running in local development mode."""
        return self.APP_ENV == "development"

    @model_validator(mode="after")
    def _fail_closed_outside_development(self) -> Self:
        if "*" in self.CORS_ORIGINS:
            raise ValueError("CORS_ORIGINS must list explicit origins; '*' is not allowed with credentials.")
        if self.is_development:
            return self
        if self.JWT_SECRET_KEY is not None and len(self.JWT_SECRET_KEY.get_secret_value()) < MIN_SECRET_CHARS:
            raise ValueError(f"JWT_SECRET_KEY must be >= {MIN_SECRET_CHARS} chars when set.")
        if self.DEBUG:
            raise ValueError(f"DEBUG must be False when APP_ENV={self.APP_ENV!r}.")
        return self


settings = Settings()
