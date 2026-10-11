import uuid

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.main import app
from app.schemas.messages import MessageCreate
from app.services.messages import create_message


async def make_user(client, username: str) -> dict:
    registered = await client.post(
        "/api/v1/auth/register",
        json={
            "username": username,
            "email": f"{username}@example.com",
            "password": "a-strong-password-123",
            "display_name": username.title(),
        },
    )
    assert registered.status_code == 201, registered.text
    login = await client.post(
        "/api/v1/auth/login",
        json={"identifier": username, "password": "a-strong-password-123"},
    )
    assert login.status_code == 200, login.text
    return {"user": registered.json(), "token": login.json()["access_token"]}


def authenticate(websocket, token: str) -> None:
    websocket.send_json(
        {
            "type": "auth.authenticate",
            "request_id": str(uuid.uuid4()),
            "payload": {"access_token": token},
        }
    )
    assert websocket.receive_json()["type"] == "connection.ready"


@pytest.mark.asyncio
async def test_websocket_auth_message_ack_and_member_broadcast(api_client) -> None:
    alice = await make_user(api_client, "wsalice")
    bob = await make_user(api_client, "wsbob")
    outsider = await make_user(api_client, "wsoutsider")
    direct = await api_client.post(
        "/api/v1/chats/direct",
        json={"user_id": bob["user"]["id"]},
        headers={"Authorization": f"Bearer {alice['token']}"},
    )
    assert direct.status_code == 200, direct.text

    with TestClient(app) as client:
        with client.websocket_connect(
            "/api/v1/ws", headers={"origin": "http://localhost:5173"}
        ) as alice_ws:
            with client.websocket_connect(
                "/api/v1/ws", headers={"origin": "http://localhost:5173"}
            ) as bob_ws:
                authenticate(alice_ws, alice["token"])
                authenticate(bob_ws, bob["token"])
                request_id = str(uuid.uuid4())
                content = "saved before broadcast"
                alice_ws.send_json(
                    {
                        "type": "message.send",
                        "request_id": request_id,
                        "payload": {
                            "chat_id": direct.json()["id"],
                            "client_message_id": str(uuid.uuid4()),
                            "content": content,
                        },
                    }
                )
                acknowledgement = alice_ws.receive_json()
                assert acknowledgement["type"] == "message.ack"
                assert acknowledgement["request_id"] == request_id
                assert acknowledgement["payload"]["message"]["content"] == content

                sender_event = alice_ws.receive_json()
                recipient_event = bob_ws.receive_json()
                assert sender_event["type"] == "message.new"
                assert recipient_event["type"] == "message.new"
                assert (
                    recipient_event["payload"]["message"]["id"]
                    == acknowledgement["payload"]["message"]["id"]
                )

        with pytest.raises(WebSocketDisconnect) as disconnect:
            with client.websocket_connect(
                "/api/v1/ws", headers={"origin": "http://localhost:5173"}
            ) as unauthenticated:
                authenticate(unauthenticated, "invalid-token")
        assert disconnect.value.code == 4401

    outsider_history = await api_client.get(
        f"/api/v1/chats/{direct.json()['id']}/messages",
        headers={"Authorization": f"Bearer {outsider['token']}"},
    )
    assert outsider_history.status_code == 404

    persisted_history = await api_client.get(
        f"/api/v1/chats/{direct.json()['id']}/messages",
        headers={"Authorization": f"Bearer {bob['token']}"},
    )
    assert persisted_history.status_code == 200
    assert persisted_history.json()["items"][0]["content"] == "saved before broadcast"


@pytest.mark.asyncio
async def test_reactions_are_persisted_and_broadcast_only_to_chat_members(
    api_client, test_session
) -> None:
    alice = await make_user(api_client, "reactalice")
    bob = await make_user(api_client, "reactbob")
    outsider = await make_user(api_client, "reactoutsider")
    direct = await api_client.post(
        "/api/v1/chats/direct",
        json={"user_id": bob["user"]["id"]},
        headers={"Authorization": f"Bearer {alice['token']}"},
    )
    chat_id = uuid.UUID(direct.json()["id"])
    message = await create_message(
        test_session,
        uuid.UUID(alice["user"]["id"]),
        MessageCreate(chat_id=chat_id, client_message_id=uuid.uuid4(), content="React to this"),
    )

    with TestClient(app) as client:
        with client.websocket_connect(
            "/api/v1/ws", headers={"origin": "http://localhost:5173"}
        ) as alice_ws:
            with client.websocket_connect(
                "/api/v1/ws", headers={"origin": "http://localhost:5173"}
            ) as bob_ws:
                authenticate(alice_ws, alice["token"])
                authenticate(bob_ws, bob["token"])
                alice_ws.send_json(
                    {
                        "type": "reaction.set",
                        "request_id": str(uuid.uuid4()),
                        "payload": {
                            "chat_id": str(chat_id),
                            "message_id": str(message.id),
                            "emoji": "❤️",
                            "active": True,
                        },
                    }
                )
                alice_event = alice_ws.receive_json()
                bob_event = bob_ws.receive_json()
                assert alice_event["type"] == bob_event["type"] == "reaction.updated"
                assert bob_event["payload"]["count"] == 1
                assert bob_event["payload"]["active"] is True

        with client.websocket_connect(
            "/api/v1/ws", headers={"origin": "http://localhost:5173"}
        ) as outsider_ws:
            authenticate(outsider_ws, outsider["token"])
            outsider_ws.send_json(
                {
                    "type": "reaction.set",
                    "request_id": str(uuid.uuid4()),
                    "payload": {
                        "chat_id": str(chat_id),
                        "message_id": str(message.id),
                        "emoji": "❤️",
                        "active": True,
                    },
                }
            )
            denied = outsider_ws.receive_json()
            assert denied["type"] == "error"
            assert denied["payload"]["code"] == "CHAT_ACCESS_DENIED"

    alice_history = await api_client.get(
        f"/api/v1/chats/{chat_id}/messages",
        headers={"Authorization": f"Bearer {alice['token']}"},
    )
    bob_history = await api_client.get(
        f"/api/v1/chats/{chat_id}/messages",
        headers={"Authorization": f"Bearer {bob['token']}"},
    )
    assert alice_history.json()["items"][0]["reactions"] == [
        {"emoji": "❤️", "count": 1, "reacted_by_me": True}
    ]
    assert bob_history.json()["items"][0]["reactions"] == [
        {"emoji": "❤️", "count": 1, "reacted_by_me": False}
    ]


@pytest.mark.asyncio
async def test_extended_message_features(api_client, test_session) -> None:
    alice = await make_user(api_client, "attachalice")
    bob = await make_user(api_client, "attachbob")
    outsider = await make_user(api_client, "attachoutsider")
    auth_alice = {"Authorization": f"Bearer {alice['token']}"}
    auth_bob = {"Authorization": f"Bearer {bob['token']}"}
    direct = await api_client.post(
        "/api/v1/chats/direct", json={"user_id": bob["user"]["id"]}, headers=auth_alice
    )
    chat_id = uuid.UUID(direct.json()["id"])
    parent = await create_message(
        test_session,
        uuid.UUID(alice["user"]["id"]),
        MessageCreate(chat_id=chat_id, client_message_id=uuid.uuid4(), content="Original message"),
    )

    muted = await api_client.patch(
        f"/api/v1/chats/{chat_id}/preferences", json={"muted": True}, headers=auth_bob
    )
    assert muted.status_code == 200 and muted.json()["muted"] is True
    listed_chats = await api_client.get("/api/v1/chats", headers=auth_bob)
    assert next(item for item in listed_chats.json()["items"] if item["id"] == str(chat_id))[
        "muted"
    ]

    upload = await api_client.post(
        f"/api/v1/chats/{chat_id}/attachments",
        content=b"small test file",
        headers={**auth_alice, "Content-Type": "text/plain", "X-File-Name": "notes.txt"},
    )
    assert upload.status_code == 201, upload.text
    attachment_id = upload.json()["id"]
    forbidden_upload = await api_client.post(
        f"/api/v1/chats/{chat_id}/attachments",
        content=b"no access",
        headers={**{"Authorization": f"Bearer {outsider['token']}"}, "X-File-Name": "x.txt"},
    )
    assert forbidden_upload.status_code == 404

    with TestClient(app) as client:
        with client.websocket_connect(
            "/api/v1/ws", headers={"origin": "http://localhost:5173"}
        ) as alice_ws:
            with client.websocket_connect(
                "/api/v1/ws", headers={"origin": "http://localhost:5173"}
            ) as bob_ws:
                authenticate(alice_ws, alice["token"])
                authenticate(bob_ws, bob["token"])
                message_id = str(uuid.uuid4())
                alice_ws.send_json(
                    {
                        "type": "message.send",
                        "request_id": str(uuid.uuid4()),
                        "payload": {
                            "chat_id": str(chat_id),
                            "client_message_id": message_id,
                            "content": "Please check this, @attachbob",
                            "reply_to_message_id": str(parent.id),
                            "attachment_ids": [attachment_id],
                        },
                    }
                )
                created = alice_ws.receive_json()
                assert created["type"] == "message.ack"
                message = created["payload"]["message"]
                assert message["reply_to"]["id"] == str(parent.id)
                assert message["mentions"][0]["username"] == "attachbob"
                assert message["attachments"][0]["filename"] == "notes.txt"
                alice_ws.receive_json()
                bob_ws.receive_json()

                download = await api_client.get(
                    message["attachments"][0]["download_url"], headers=auth_bob
                )
                assert download.status_code == 200
                assert download.content == b"small test file"

                bob_ws.send_json(
                    {
                        "type": "message.edit",
                        "request_id": str(uuid.uuid4()),
                        "payload": {"message_id": message["id"], "content": "forbidden edit"},
                    }
                )
                denied_edit = bob_ws.receive_json()
                assert denied_edit["type"] == "error"
                assert denied_edit["payload"]["code"] == "MESSAGE_EDIT_FORBIDDEN"

                bob_ws.send_json(
                    {
                        "type": "chat.read",
                        "request_id": str(uuid.uuid4()),
                        "payload": {"chat_id": str(chat_id), "message_id": message["id"]},
                    }
                )
                assert alice_ws.receive_json()["type"] == "chat.read.updated"
                assert bob_ws.receive_json()["type"] == "chat.read.updated"

                alice_ws.send_json(
                    {
                        "type": "message.edit",
                        "request_id": str(uuid.uuid4()),
                        "payload": {"message_id": message["id"], "content": "Updated message"},
                    }
                )
                updated_for_alice = alice_ws.receive_json()
                updated_for_bob = bob_ws.receive_json()
                assert updated_for_alice["type"] == "message.updated"
                assert updated_for_bob["payload"]["message"]["edited"] is True
                assert updated_for_bob["payload"]["message"]["mentions"] == []

                alice_ws.send_json(
                    {
                        "type": "message.delete",
                        "request_id": str(uuid.uuid4()),
                        "payload": {"message_id": message["id"]},
                    }
                )
                deleted = alice_ws.receive_json()
                assert deleted["payload"]["message"]["deleted_at"] is not None
                bob_ws.receive_json()

    history = await api_client.get(f"/api/v1/chats/{chat_id}/messages", headers=auth_alice)
    saved = next(item for item in history.json()["items"] if item["id"] == message["id"])
    assert saved["read_by"] == [bob["user"]["id"]]
    assert saved["content"] == "Сообщение удалено"
    hidden_download = await api_client.get(
        message["attachments"][0]["download_url"], headers=auth_bob
    )
    assert hidden_download.status_code == 404
