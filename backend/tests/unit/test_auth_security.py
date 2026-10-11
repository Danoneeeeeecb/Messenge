import uuid

import jwt
import pytest
from pydantic import ValidationError

from app.core.config import Settings, get_settings
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from app.schemas.chats import GroupChatCreate
from app.schemas.messages import MessageCreate
from app.schemas.users import UserCreate


def test_password_hash_uses_argon2_and_verifies_password() -> None:
    encoded = hash_password("a-strong-password-123")

    assert encoded.startswith("$argon2id$")
    assert verify_password("a-strong-password-123", encoded)
    assert not verify_password("incorrect-password", encoded)


def test_access_token_contains_required_claims_and_round_trips_user_id() -> None:
    user_id = uuid.uuid4()
    token = create_access_token(user_id)
    claims = jwt.decode(
        token,
        get_settings().jwt_secret_key.get_secret_value(),
        algorithms=[get_settings().jwt_algorithm],
    )

    assert set(("sub", "iat", "exp", "jti")).issubset(claims)
    assert decode_access_token(token) == user_id


def test_access_token_rejects_tampered_signature() -> None:
    token = create_access_token(uuid.uuid4())
    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(f"{token[:-1]}x")


def test_jwt_settings_reject_weak_secret_and_unapproved_algorithm() -> None:
    with pytest.raises(ValidationError):
        Settings(jwt_secret_key="too-short")
    with pytest.raises(ValidationError):
        Settings(jwt_secret_key="s" * 40, jwt_algorithm="none")


def test_user_input_is_normalized() -> None:
    payload = UserCreate(
        username=" Alice_01 ",
        email="ALICE@example.com",
        password="a-strong-password-123",
        display_name=" Alice ",
    )

    assert payload.username == "alice_01"
    assert payload.email == "alice@example.com"
    assert payload.display_name == "Alice"


@pytest.mark.parametrize(
    "overrides",
    [
        {"username": "x"},
        {"username": "bad name"},
        {"email": "not-an-email"},
        {"password": "short"},
        {"display_name": "   "},
    ],
)
def test_invalid_registration_data_is_rejected(overrides: dict[str, str]) -> None:
    fields = {
        "username": "alice",
        "email": "alice@example.com",
        "password": "a-strong-password-123",
        "display_name": "Alice",
    }
    fields.update(overrides)

    with pytest.raises(ValidationError):
        UserCreate(**fields)


def test_group_chat_schema_trims_title_and_rejects_duplicate_members() -> None:
    first_id = uuid.uuid4()
    second_id = uuid.uuid4()
    payload = GroupChatCreate(title="  Project Team  ", member_ids=[first_id, second_id])

    assert payload.title == "Project Team"
    with pytest.raises(ValidationError):
        GroupChatCreate(title="Team", member_ids=[first_id, first_id])


def test_message_schema_rejects_blank_content() -> None:
    with pytest.raises(ValidationError):
        MessageCreate(chat_id=uuid.uuid4(), client_message_id=uuid.uuid4(), content="  \n")
