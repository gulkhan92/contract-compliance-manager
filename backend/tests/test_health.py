import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_check_returns_ok(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["app_name"] == "ObliTrack API"
    assert body["environment"] == "development"


@pytest.mark.asyncio
async def test_openapi_schema_is_served(client: AsyncClient) -> None:
    response = await client.get("/docs")

    assert response.status_code == 200
