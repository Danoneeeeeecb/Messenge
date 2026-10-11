import pytest


async def register(client, username: str) -> dict:
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "username": username,
            "email": f"{username}@example.com",
            "password": "a-strong-password-123",
            "display_name": username.title(),
        },
    )
    assert response.status_code == 201, response.text
    login = await client.post(
        "/api/v1/auth/login",
        json={"identifier": username, "password": "a-strong-password-123"},
    )
    assert login.status_code == 200, login.text
    return {"user": response.json(), "token": login.json()["access_token"]}


def auth(user: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {user['token']}"}


@pytest.mark.asyncio
async def test_direct_chat_is_unique_and_hidden_from_non_members(api_client) -> None:
    alice = await register(api_client, "alice")
    bob = await register(api_client, "bob")
    outsider = await register(api_client, "charlie")

    created = await api_client.post(
        "/api/v1/chats/direct",
        json={"user_id": bob["user"]["id"]},
        headers=auth(alice),
    )
    assert created.status_code == 200, created.text
    assert created.json()["type"] == "direct"

    repeated = await api_client.post(
        "/api/v1/chats/direct",
        json={"user_id": alice["user"]["id"]},
        headers=auth(bob),
    )
    assert repeated.status_code == 200
    assert repeated.json()["id"] == created.json()["id"]

    members = await api_client.get(
        f"/api/v1/chats/{created.json()['id']}/members", headers=auth(alice)
    )
    assert members.status_code == 200
    assert len(members.json()) == 2

    chat_list = await api_client.get("/api/v1/chats", headers=auth(alice))
    listed_chat = next(
        item for item in chat_list.json()["items"] if item["id"] == created.json()["id"]
    )
    assert listed_chat["peer"]["id"] == bob["user"]["id"]
    assert listed_chat["peer"]["display_name"] == "Bob"
    assert listed_chat["last_message"] is None

    hidden = await api_client.get(f"/api/v1/chats/{created.json()['id']}", headers=auth(outsider))
    assert hidden.status_code == 404

    self_chat = await api_client.post(
        "/api/v1/chats/direct",
        json={"user_id": alice["user"]["id"]},
        headers=auth(alice),
    )
    assert self_chat.status_code == 409


@pytest.mark.asyncio
async def test_group_roles_and_last_admin_rule(api_client) -> None:
    owner = await register(api_client, "owner")
    member = await register(api_client, "member")
    third = await register(api_client, "third")

    created = await api_client.post(
        "/api/v1/chats/group",
        json={"title": "  Project Team  ", "member_ids": [member["user"]["id"]]},
        headers=auth(owner),
    )
    assert created.status_code == 201, created.text
    assert created.json()["title"] == "Project Team"
    chat_id = created.json()["id"]

    members = await api_client.get(f"/api/v1/chats/{chat_id}/members", headers=auth(owner))
    roles = {item["user_id"]: item["role"] for item in members.json()}
    assert roles[owner["user"]["id"]] == "admin"
    assert roles[member["user"]["id"]] == "member"

    denied = await api_client.post(
        f"/api/v1/chats/{chat_id}/members",
        json={"user_id": third["user"]["id"]},
        headers=auth(member),
    )
    assert denied.status_code == 403

    added = await api_client.post(
        f"/api/v1/chats/{chat_id}/members",
        json={"user_id": third["user"]["id"]},
        headers=auth(owner),
    )
    assert added.status_code == 201, added.text

    removed = await api_client.delete(
        f"/api/v1/chats/{chat_id}/members/{member['user']['id']}", headers=auth(owner)
    )
    assert removed.status_code == 204

    last_admin = await api_client.delete(
        f"/api/v1/chats/{chat_id}/members/{owner['user']['id']}", headers=auth(owner)
    )
    assert last_admin.status_code == 409

    outsider_result = await api_client.get("/api/v1/chats", headers=auth(member))
    assert outsider_result.status_code == 200
    assert outsider_result.json()["items"] == []
