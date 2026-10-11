import pytest


@pytest.mark.asyncio
async def test_register_login_and_read_current_user(api_client) -> None:
    registration = {
        "username": "Alice",
        "email": "ALICE@example.com",
        "password": "a-strong-password-123",
        "display_name": "Alice Example",
    }
    registered = await api_client.post("/api/v1/auth/register", json=registration)

    assert registered.status_code == 201
    assert registered.json()["username"] == "alice"
    assert registered.json()["email"] == "alice@example.com"
    assert "password_hash" not in registered.json()
    assert "password" not in registered.json()

    login = await api_client.post(
        "/api/v1/auth/login",
        json={"identifier": "ALICE", "password": registration["password"]},
    )
    assert login.status_code == 200
    token_data = login.json()
    assert token_data["token_type"] == "bearer"
    assert token_data["expires_in"] > 0

    current_user = await api_client.get(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {token_data['access_token']}"},
    )
    assert current_user.status_code == 200
    assert current_user.json()["id"] == registered.json()["id"]


@pytest.mark.asyncio
async def test_duplicate_registration_and_invalid_login_are_rejected(api_client) -> None:
    registration = {
        "username": "bob",
        "email": "bob@example.com",
        "password": "a-strong-password-123",
        "display_name": "Bob",
    }
    assert (await api_client.post("/api/v1/auth/register", json=registration)).status_code == 201
    duplicate = await api_client.post("/api/v1/auth/register", json=registration)
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "REGISTRATION_CONFLICT"

    bad_login = await api_client.post(
        "/api/v1/auth/login", json={"identifier": "bob", "password": "wrong-password"}
    )
    assert bad_login.status_code == 401
    assert bad_login.json()["error"]["code"] == "INVALID_CREDENTIALS"


@pytest.mark.asyncio
async def test_user_search_is_authenticated_and_does_not_expose_email(api_client) -> None:
    for username in ("searcher", "searchfriend"):
        await api_client.post(
            "/api/v1/auth/register",
            json={
                "username": username,
                "email": f"{username}@example.com",
                "password": "a-strong-password-123",
                "display_name": username.title(),
            },
        )
    login = await api_client.post(
        "/api/v1/auth/login",
        json={"identifier": "searcher", "password": "a-strong-password-123"},
    )
    token = login.json()["access_token"]

    results = await api_client.get(
        "/api/v1/users/search?q=search",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert results.status_code == 200
    assert [item["username"] for item in results.json()] == ["searchfriend"]
    assert "email" not in results.json()[0]
