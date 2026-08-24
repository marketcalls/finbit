"""Application settings for FinBit.

Every tunable is read from the repo root .env file (one directory above
backend/) or from real environment variables, which win over the file.

Importing this module never fails when PERPLEXITY_API_KEY is missing. The API
starts fine without a key, and only the ingestion pipeline refuses to run.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

APP_DIR: Path = Path(__file__).resolve().parent
BACKEND_DIR: Path = APP_DIR.parent
REPO_ROOT: Path = BACKEND_DIR.parent

ENV_FILE: Path = REPO_ROOT / ".env"
SCHEMA_FILE: Path = APP_DIR / "schema.sql"
DEFAULT_DB_PATH: Path = BACKEND_DIR / "finbit.db"
DEFAULT_CORS_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173"


class Settings(BaseSettings):
    """Runtime configuration, all overridable from the environment."""

    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )

    # Perplexity Agent API (contract section 6).
    perplexity_api_key: str = ""
    perplexity_model: str = "perplexity/sonar"
    perplexity_base_url: str = "https://api.perplexity.ai"
    perplexity_timeout_seconds: float = 180.0

    # Storage and transport.
    db_path: Path = DEFAULT_DB_PATH
    cors_origins_csv: str = Field(default=DEFAULT_CORS_ORIGINS, alias="CORS_ORIGINS")

    # Ingestion and scoring schedule (contract section 9).
    ingest_enabled: bool = True
    ingest_interval_minutes: int = 15
    ingest_queries_per_cycle: int = 4
    ingest_max_stories_per_query: int = 6
    ingest_concurrency: int = 3
    rescore_interval_minutes: int = 30

    @field_validator("db_path", mode="before")
    @classmethod
    def _coerce_db_path(cls, value: object) -> object:
        """Accept a relative DB_PATH and anchor it to the backend directory."""
        if value is None or value == "":
            return DEFAULT_DB_PATH
        path = Path(str(value)).expanduser()
        if not path.is_absolute():
            path = BACKEND_DIR / path
        return path

    @field_validator("perplexity_base_url", mode="before")
    @classmethod
    def _clean_base_url(cls, value: object) -> object:
        if value is None or str(value).strip() == "":
            return "https://api.perplexity.ai"
        return str(value).strip().rstrip("/")

    @field_validator(
        "ingest_interval_minutes",
        "ingest_queries_per_cycle",
        "ingest_max_stories_per_query",
        "ingest_concurrency",
        "rescore_interval_minutes",
        mode="after",
    )
    @classmethod
    def _at_least_one(cls, value: int) -> int:
        return max(1, int(value))

    @property
    def cors_origins(self) -> list[str]:
        """Allowed browser origins, parsed from a comma separated string."""
        raw = self.cors_origins_csv.strip()
        if raw.startswith("[") and raw.endswith("]"):
            raw = raw[1:-1]
        origins: list[str] = []
        for part in raw.split(","):
            origin = part.strip().strip('"').strip("'").rstrip("/")
            if origin and origin not in origins:
                origins.append(origin)
        return origins or [o for o in DEFAULT_CORS_ORIGINS.split(",")]

    @property
    def perplexity_agent_url(self) -> str:
        """Full URL of the Perplexity Agent endpoint."""
        return f"{self.perplexity_base_url.rstrip('/')}/v1/agent"

    @property
    def has_perplexity_key(self) -> bool:
        return bool(self.perplexity_api_key.strip())

    @property
    def schema_path(self) -> Path:
        return SCHEMA_FILE

    def require_perplexity_api_key(self) -> str:
        """Return the API key, or raise when it is not configured.

        Call this at pipeline run time, never at import time, so the API keeps
        serving cached articles on a machine with no key.
        """
        key = self.perplexity_api_key.strip()
        if not key:
            raise RuntimeError(
                "PERPLEXITY_API_KEY is not set. Add it to the .env file at the "
                "repo root before running the ingestion pipeline."
            )
        return key


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings singleton."""
    return Settings()


def reset_settings_cache() -> None:
    """Drop the cached settings, used by tests that patch the environment."""
    get_settings.cache_clear()


__all__ = [
    "APP_DIR",
    "BACKEND_DIR",
    "DEFAULT_CORS_ORIGINS",
    "DEFAULT_DB_PATH",
    "ENV_FILE",
    "REPO_ROOT",
    "SCHEMA_FILE",
    "Settings",
    "get_settings",
    "reset_settings_cache",
]
