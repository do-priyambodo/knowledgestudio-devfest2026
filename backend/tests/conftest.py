"""Shared fixtures for the HTTP unit tests. No database, cache or model is touched."""

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from api.main import app


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    """An entered httpx client bound to the ASGI app (the lifespan does not run)."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http
