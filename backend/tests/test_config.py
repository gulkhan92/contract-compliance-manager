import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_production_rejects_default_jwt_secret() -> None:
    with pytest.raises(ValidationError, match="JWT_SECRET_KEY"):
        Settings(
            environment="production",
            database_url="postgresql+asyncpg://real_user:real_pass@prod-host:5432/oblitrack",
        )


def test_production_rejects_default_db_credentials() -> None:
    with pytest.raises(ValidationError, match="DATABASE_URL"):
        Settings(
            environment="production",
            jwt_secret_key="a" * 32,
        )


def test_production_accepts_properly_configured_secrets() -> None:
    settings = Settings(
        environment="production",
        jwt_secret_key="a" * 32,
        database_url="postgresql+asyncpg://real_user:real_pass@prod-host:5432/oblitrack",
    )
    assert settings.environment == "production"


def test_development_allows_insecure_defaults() -> None:
    settings = Settings(environment="development")
    assert settings.jwt_secret_key == "dev-only-insecure-secret-change-me"
