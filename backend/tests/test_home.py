import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_root_endpoint_returns_ok():
    # Arrange
    transport = ASGITransport(app=app)

    # Act
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/")

    # Assert
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == "refund-request-processor"


@pytest.mark.asyncio
async def test_root_endpoint_post_method_not_allowed():
    # Arrange
    transport = ASGITransport(app=app)

    # Act
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/")

    # Assert
    assert response.status_code == 405


@pytest.mark.asyncio
async def test_health_endpoint_returns_healthy():
    # Arrange
    transport = ASGITransport(app=app)

    # Act
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    # Assert
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"


@pytest.mark.asyncio
async def test_health_endpoint_post_method_not_allowed():
    # Arrange
    transport = ASGITransport(app=app)

    # Act
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/health")

    # Assert
    assert response.status_code == 405


@pytest.mark.asyncio
async def test_nonexistent_route_returns_not_found():
    # Arrange
    transport = ASGITransport(app=app)

    # Act
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/nonexistent")

    # Assert
    assert response.status_code == 404
