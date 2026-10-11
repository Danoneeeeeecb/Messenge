import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.messages import MessageCreate
from app.services.messages import MessageConflict, create_message


async def make_user(client, username: str) -> dict:
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
async def test_message_idempotency_history_cursor_and_search(
    api_client, test_session: AsyncSession
) -> None:
    sender = await make_user(api_client, "sender")
    recipient = await make_user(api_client, "recipient")
    outsider = await make_user(api_client, "outsider")
    direct = await api_client.post(
        "/api/v1/chats/direct",
        json={"user_id": recipient["user"]["id"]},
        headers=auth(sender),
    )
    assert direct.status_code == 200, direct.text
    chat_id = uuid.UUID(direct.json()["id"])
    sender_id = uuid.UUID(sender["user"]["id"])

    original_payload = MessageCreate(
        chat_id=chat_id, client_message_id=uuid.uuid4(), content="needle one"
    )
    original = await create_message(test_session, sender_id, original_payload)
    replay = await create_message(test_session, sender_id, original_payload)
    assert original.id == replay.id
    base_time = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)
    original.created_at = base_time
    await test_session.commit()

    for index, content in enumerate(["needle two", "last note"], start=1):
        message = await create_message(
            test_session,
            sender_id,
            MessageCreate(chat_id=chat_id, client_message_id=uuid.uuid4(), content=content),
        )
        message.created_at = base_time + timedelta(seconds=index)
        await test_session.commit()

    chat_list = await api_client.get("/api/v1/chats", headers=auth(recipient))
    listed_chat = next(item for item in chat_list.json()["items"] if item["id"] == str(chat_id))
    assert listed_chat["last_message"] == "last note"

    conflict = MessageCreate(
        chat_id=chat_id,
        client_message_id=original_payload.client_message_id,
        content="different payload",
    )
    with pytest.raises(MessageConflict):
        await create_message(test_session, sender_id, conflict)

    first_page = await api_client.get(
        f"/api/v1/chats/{chat_id}/messages?limit=2", headers=auth(recipient)
    )
    assert first_page.status_code == 200, first_page.text
    assert [item["content"] for item in first_page.json()["items"]] == [
        "needle two",
        "last note",
    ]
    next_cursor = first_page.json()["next_cursor"]
    assert next_cursor

    older_page = await api_client.get(
        f"/api/v1/chats/{chat_id}/messages?limit=2&before={next_cursor}",
        headers=auth(recipient),
    )
    assert older_page.status_code == 200
    assert [item["content"] for item in older_page.json()["items"]] == ["needle one"]

    search = await api_client.get(
        f"/api/v1/chats/{chat_id}/messages/search?q=needle", headers=auth(recipient)
    )
    assert [item["content"] for item in search.json()["items"]] == [
        "needle one",
        "needle two",
    ]

    forbidden = await api_client.get(f"/api/v1/chats/{chat_id}/messages", headers=auth(outsider))
    assert forbidden.status_code == 404
