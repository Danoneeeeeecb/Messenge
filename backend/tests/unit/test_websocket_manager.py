import uuid

import pytest

from app.websocket.manager import WebSocketManager


class FakeWebSocket:
    def __init__(self) -> None:
        self.events: list[dict] = []

    async def send_json(self, event: dict) -> None:
        self.events.append(event)


@pytest.mark.asyncio
async def test_manager_caps_connections_and_limits_message_rate() -> None:
    manager = WebSocketManager(max_connections_per_user=1, rate_count=2, rate_window=30)
    user_id = uuid.uuid4()
    first_socket = FakeWebSocket()
    second_socket = FakeWebSocket()

    first = await manager.register(first_socket, user_id)
    second = await manager.register(second_socket, user_id)
    assert first is not None
    assert second is None

    assert await manager.allow_message(user_id)
    assert await manager.allow_message(user_id)
    assert not await manager.allow_message(user_id)

    await manager.unregister(first)
    assert await manager.register(second_socket, user_id) is not None


@pytest.mark.asyncio
async def test_manager_broadcasts_to_each_registered_connection() -> None:
    manager = WebSocketManager(max_connections_per_user=2, rate_count=10, rate_window=10)
    user_id = uuid.uuid4()
    first_socket = FakeWebSocket()
    second_socket = FakeWebSocket()
    await manager.register(first_socket, user_id)
    await manager.register(second_socket, user_id)

    await manager.broadcast([user_id, user_id], {"type": "message.new"})

    assert first_socket.events == [{"type": "message.new"}]
    assert second_socket.events == [{"type": "message.new"}]
