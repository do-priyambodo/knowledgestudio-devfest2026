"""Unit tests for the FastAPI HTTP surface and fail-closed production settings."""

import pytest
from httpx import AsyncClient
from pydantic import ValidationError

from api.platform.config import Settings, settings


async def test_health_endpoint(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


async def test_root_endpoint(client: AsyncClient) -> None:
    response = await client.get("/")
    assert response.status_code == 200
    assert response.json()["status"] == "success"


async def test_cors_allows_only_configured_origins(client: AsyncClient) -> None:
    allowed = await client.get("/health", headers={"Origin": settings.CORS_ORIGINS[0]})
    denied = await client.get("/health", headers={"Origin": "https://evil.invalid"})
    assert allowed.headers.get("access-control-allow-origin") == settings.CORS_ORIGINS[0]
    assert "access-control-allow-origin" not in denied.headers


def test_settings_defaults_are_safe() -> None:
    fresh = Settings.model_validate({"APP_ENV": "development"})
    assert fresh.DEBUG is False
    assert "*" not in fresh.CORS_ORIGINS


@pytest.mark.parametrize(
    "overrides",
    [
        {"APP_ENV": "production", "JWT_SECRET_KEY": "too-short"},
        {"APP_ENV": "production", "DEBUG": True},
        {"APP_ENV": "development", "CORS_ORIGINS": ["*"]},
    ],
)
def test_settings_fail_closed(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate(overrides)
