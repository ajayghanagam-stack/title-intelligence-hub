import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import create_app


@pytest.mark.asyncio
async def test_health_check():
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/health")
        assert response.status_code == 200
        assert response.json() == {"status": "healthy"}


@pytest.mark.asyncio
async def test_readiness_check(client):
    response = await client.get("/api/v1/health/ready")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    assert data["checks"]["database"]["status"] == "ok"
    assert data["checks"]["database"]["latency_ms"] >= 0
    assert data["checks"]["micro_apps"]["count"] >= 1
    assert "title-intelligence" in data["checks"]["micro_apps"]["slugs"]


@pytest.mark.asyncio
async def test_request_id_generated(client):
    """Responses include a generated X-Request-Id when none is sent."""
    response = await client.get("/api/v1/health")
    assert "x-request-id" in response.headers
    assert len(response.headers["x-request-id"]) > 0


@pytest.mark.asyncio
async def test_request_id_propagated(client):
    """When X-Request-Id is sent, the same value is echoed back."""
    response = await client.get(
        "/api/v1/health",
        headers={"X-Request-Id": "my-trace-123"},
    )
    assert response.headers["x-request-id"] == "my-trace-123"
