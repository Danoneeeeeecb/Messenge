import uuid

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.main import app


def test_websocket_rejects_invalid_token_before_business_events() -> None:
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as disconnect:
            with client.websocket_connect(
                "/api/v1/ws", headers={"origin": "http://localhost:5173"}
            ) as websocket:
                websocket.send_json(
                    {
                        "type": "auth.authenticate",
                        "request_id": str(uuid.uuid4()),
                        "payload": {"access_token": "invalid-token"},
                    }
                )
                websocket.receive_json()

    assert disconnect.value.code == 4401
