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

# A secret that still carries the .env.example placeholder counts as unset.
# Shipping the sample value is the most likely configuration mistake, so it is
# treated exactly like an empty string rather than silently accepted.
PLACEHOLDER_PREFIX: str = "change-me"

SECURITY_KEY_NAMES: tuple[str, ...] = (
    "APP_KEY_MOBILE",
    "APP_KEY_WEB",
    "DEVICE_MASTER_KEY",
    "JWT_SECRET",
)
"""The four secrets a signed deployment cannot start without (contract 2, 3.9)."""

UNSIGNED_MODE_WARNING: str = (
    "REQUIRE_SIGNED_REQUESTS is false. Requests are accepted with an app key "
    "and a bearer token only, with no HMAC signature and no replay protection. "
    "This is a development-only switch. Never run a deployment this way."
)


def is_placeholder(value: str | None) -> bool:
    """True when a secret is empty or still holds its change-me placeholder."""
    text = (value or "").strip()
    return not text or text.lower().startswith(PLACEHOLDER_PREFIX)


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
    # The live Agent API account answers with x-ratelimit-limit: 1, so more
    # than one request in flight earns a 429. 1 is the safe default.
    ingest_concurrency: int = 1
    rescore_interval_minutes: int = 30

    # Cold start (contract section 13).
    ingest_on_startup: bool = True
    allow_admin_ingest_from_ui: bool = True

    # Security core (contract 2, sections 3.2 and 3.9). Every secret defaults to
    # an empty string so importing this module still never fails on a machine
    # that has not been configured. validate_security() is what refuses to start
    # a deployment that is missing one.
    app_key_mobile: str = ""
    app_key_web: str = ""
    device_master_key: str = ""
    jwt_secret: str = ""
    admin_bootstrap_username: str = ""
    admin_bootstrap_password: str = ""
    signature_skew_seconds: int = 120
    nonce_ttl_seconds: int = 300
    require_signed_requests: bool = True

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

    @field_validator("signature_skew_seconds", "nonce_ttl_seconds", mode="after")
    @classmethod
    def _positive_seconds(cls, value: int) -> int:
        """A zero or negative window would disable replay protection entirely."""
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
    def missing_key_detail(self) -> str:
        """The message shown when ingestion is asked for without a key."""
        return (
            "PERPLEXITY_API_KEY is not set. Add it to the .env file at the repo "
            "root before running the ingestion pipeline."
        )

    @property
    def ingest_available(self) -> bool:
        """True when a cycle could actually run: enabled and holding a key."""
        return self.ingest_enabled and self.has_perplexity_key

    @property
    def ingest_unavailable_reason(self) -> str | None:
        """Why ingestion cannot run, or None when it can (contract 13.4).

        The frontend empty state shows this instead of blaming the network.
        """
        if not self.has_perplexity_key:
            return self.missing_key_detail
        if not self.ingest_enabled:
            return "INGEST_ENABLED is false, so scheduled ingestion is turned off."
        return None

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
            raise RuntimeError(self.missing_key_detail)
        return key

    # -----------------------------------------------------------------------
    # Security core (contract 2, section 3)
    # -----------------------------------------------------------------------

    @property
    def app_keys(self) -> dict[str, str]:
        """Configured app key to app id, skipping anything still unset.

        An unset key must never match an empty or placeholder X-App-Key header,
        so placeholders are dropped here rather than compared later.
        """
        pairs = ((self.app_key_mobile, "mobile"), (self.app_key_web, "web"))
        return {key.strip(): app_id for key, app_id in pairs if not is_placeholder(key)}

    @property
    def has_admin_bootstrap(self) -> bool:
        """True when both bootstrap variables are set (contract 2, 3.8)."""
        return bool(
            self.admin_bootstrap_username.strip()
            and self.admin_bootstrap_password.strip()
        )

    @property
    def security_configured(self) -> bool:
        """True when every secret a signed deployment needs is present."""
        return not self.validate_security()

    def validate_security(self) -> list[str]:
        """Return the configuration problems that must stop startup.

        Empty list means the process may start. Signed mode is the only mode
        that requires the four secrets, so an unsigned development run returns
        no problems and the caller logs UNSIGNED_MODE_WARNING instead.

        The returned sentences name the missing variable and never quote its
        value, so this can be logged safely.
        """
        if not self.require_signed_requests:
            return []
        values = {
            "APP_KEY_MOBILE": self.app_key_mobile,
            "APP_KEY_WEB": self.app_key_web,
            "DEVICE_MASTER_KEY": self.device_master_key,
            "JWT_SECRET": self.jwt_secret,
        }
        problems: list[str] = []
        for name in SECURITY_KEY_NAMES:
            if is_placeholder(values[name]):
                problems.append(
                    f"{name} is empty or still set to its change-me placeholder. "
                    f"Set a real value in the .env file at the repo root, or set "
                    f"REQUIRE_SIGNED_REQUESTS=false for local development only."
                )
        return problems


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
    "PLACEHOLDER_PREFIX",
    "REPO_ROOT",
    "SCHEMA_FILE",
    "SECURITY_KEY_NAMES",
    "Settings",
    "UNSIGNED_MODE_WARNING",
    "get_settings",
    "is_placeholder",
    "reset_settings_cache",
]
