import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_health_and_protected_profile_endpoints() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        live = await client.get("/api/v1/health/live")
        missing_token = await client.get("/api/v1/users/me")
        invalid_token = await client.get(
            "/api/v1/users/me", headers={"Authorization": "Bearer not-a-jwt"}
        )

    assert live.status_code == 200
    assert live.json() == {"status": "ok"}
    assert missing_token.status_code == 401
    assert invalid_token.status_code == 401
    assert invalid_token.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"


@pytest.mark.asyncio
async def test_invalid_registration_request_uses_standard_error_shape() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "username": "x",
                "email": "not-an-email",
                "password": "short",
                "display_name": "",
            },
        )

    assert response.status_code == 422
    assert response.json() == {
        "error": {"code": "INVALID_REQUEST", "message": "Request validation failed"}
    }
