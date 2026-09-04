"""Application configuration.

All configuration is loaded from environment variables (optionally via a
local `.env` file, never committed) using pydantic-settings. See
`.env.example` at the repo root for the full list of variables a deployment
must provide.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Placeholder-only values: fine for local dev, never acceptable once
# ENVIRONMENT=production — see Settings._forbid_insecure_defaults_in_production.
_INSECURE_DEV_JWT_SECRET = "dev-only-insecure-secret-change-me"
_INSECURE_DEV_DB_CREDENTIALS = "oblitrack:oblitrack@"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- App ---
    app_name: str = "ObliTrack API"
    environment: Literal["development", "test", "staging", "production"] = "development"
    api_v1_prefix: str = "/api/v1"
    cors_allowed_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    # --- Database (wired up in Phase 1) ---
    database_url: str = "postgresql+asyncpg://oblitrack:oblitrack@localhost:5432/oblitrack"

    # --- Auth (wired up in Phase 2) ---
    jwt_secret_key: str = _INSECURE_DEV_JWT_SECRET
    jwt_access_token_expire_minutes: int = 15
    jwt_refresh_token_expire_days: int = 7

    # --- Document storage (wired up in Phase 3) ---
    storage_root: str = "storage"

    # --- Local embeddings (wired up in Phase 4) ---
    # bge-base-en-v1.5 produces 768-dim vectors, matching the
    # contract_chunks.embedding / clause_precedent_cache.embedding column
    # width fixed in the Phase 1 migration — changing this requires a new
    # migration to match.
    embedding_model_name: str = "BAAI/bge-base-en-v1.5"

    # --- LLM providers (wired up in Phase 5) ---
    groq_api_key: str | None = None
    gemini_api_key: str | None = None

    # --- SMTP (wired up in Phase 7) ---
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from_address: str | None = None

    @model_validator(mode="after")
    def _forbid_insecure_defaults_in_production(self) -> "Settings":
        """Fail fast at startup rather than silently running production
        traffic on a guessable JWT signing secret or default DB
        credentials — see docs/CONTRACT_CLM_BUILD_PLAN.md §6.7."""
        if self.environment != "production":
            return self

        problems: list[str] = []
        if self.jwt_secret_key == _INSECURE_DEV_JWT_SECRET or len(self.jwt_secret_key) < 32:
            problems.append(
                "JWT_SECRET_KEY must be set to a unique, random value of at least 32 "
                "characters when ENVIRONMENT=production."
            )
        if _INSECURE_DEV_DB_CREDENTIALS in self.database_url:
            problems.append(
                "DATABASE_URL is still using the default dev credentials "
                "(oblitrack:oblitrack) — set real production credentials."
            )
        if problems:
            raise ValueError(" ".join(problems))
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
