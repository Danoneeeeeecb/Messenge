import asyncio
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field

from fastapi import WebSocket


@dataclass(eq=False)
class Connection:
    websocket: WebSocket
    user_id: uuid.UUID
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class WebSocketManager:
    """Process-local registry for active client connections and send limits."""

    def __init__(self, max_connections_per_user: int, rate_count: int, rate_window: int) -> None:
        self._connections: dict[uuid.UUID, set[Connection]] = defaultdict(set)
        self._message_times: dict[uuid.UUID, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()
        self._max_connections_per_user = max_connections_per_user
        self._rate_count = rate_count
        self._rate_window = rate_window

    async def register(self, websocket: WebSocket, user_id: uuid.UUID) -> Connection | None:
        async with self._lock:
            connections = self._connections[user_id]
            if len(connections) >= self._max_connections_per_user:
                return None
            connection = Connection(websocket=websocket, user_id=user_id)
            connections.add(connection)
            return connection

    async def unregister(self, connection: Connection) -> None:
        async with self._lock:
            connections = self._connections.get(connection.user_id)
            if connections is not None:
                connections.discard(connection)
                if not connections:
                    self._connections.pop(connection.user_id, None)

    async def allow_message(self, user_id: uuid.UUID) -> bool:
        now = time.monotonic()
        async with self._lock:
            events = self._message_times[user_id]
            cutoff = now - self._rate_window
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= self._rate_count:
                return False
            events.append(now)
            return True

    async def send(self, connection: Connection, event: dict) -> None:
        async with connection.send_lock:
            await connection.websocket.send_json(event)

    async def broadcast(self, user_ids: list[uuid.UUID], event: dict) -> None:
        async with self._lock:
            recipients = [
                connection
                for user_id in set(user_ids)
                for connection in self._connections.get(user_id, set())
            ]
        if not recipients:
            return
        results = await asyncio.gather(
            *(self.send(connection, event) for connection in recipients), return_exceptions=True
        )
        for connection, result in zip(recipients, results, strict=True):
            if isinstance(result, Exception):
                await self.unregister(connection)
