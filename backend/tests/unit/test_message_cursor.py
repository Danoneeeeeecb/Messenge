import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.services.messages import (
    InvalidMessageCursor,
    decode_message_cursor,
    encode_message_cursor,
)


def test_message_cursor_round_trips_message_position() -> None:
    message = SimpleNamespace(
        id=uuid.uuid4(),
        created_at=datetime(2026, 10, 11, 12, 30, tzinfo=UTC),
    )

    assert decode_message_cursor(encode_message_cursor(message)) == (
        message.created_at,
        message.id,
    )


@pytest.mark.parametrize("cursor", ["not-a-cursor", "", "e30"])
def test_message_cursor_rejects_malformed_input(cursor: str) -> None:
    with pytest.raises(InvalidMessageCursor):
        decode_message_cursor(cursor)
