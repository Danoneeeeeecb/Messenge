import uuid
from typing import Any

from pydantic import BaseModel, Field, field_validator


class ClientEvent(BaseModel):
    type: str = Field(min_length=1, max_length=64)
    request_id: uuid.UUID
    payload: dict[str, Any]


class AuthenticatePayload(BaseModel):
    access_token: str = Field(min_length=1, max_length=8_192)


class MessageSendPayload(BaseModel):
    chat_id: uuid.UUID
    client_message_id: uuid.UUID
    content: str = Field(max_length=10_000)
    reply_to_message_id: uuid.UUID | None = None
    attachment_ids: list[uuid.UUID] = Field(default_factory=list, max_length=10)

    @field_validator("attachment_ids")
    @classmethod
    def require_distinct_attachments(cls, value: list[uuid.UUID]) -> list[uuid.UUID]:
        if len(value) != len(set(value)):
            raise ValueError("Attachment ids must be unique")
        return value


class ReactionSetPayload(BaseModel):
    chat_id: uuid.UUID
    message_id: uuid.UUID
    emoji: str = Field(min_length=1, max_length=16)
    active: bool


class ChatReadPayload(BaseModel):
    chat_id: uuid.UUID
    message_id: uuid.UUID


class MessageEditPayload(BaseModel):
    message_id: uuid.UUID
    content: str = Field(min_length=1, max_length=10_000)

    @field_validator("content")
    @classmethod
    def require_nonblank_content(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Message cannot be blank")
        return value


class MessageDeletePayload(BaseModel):
    message_id: uuid.UUID


class ServerEvent(BaseModel):
    type: str
    request_id: uuid.UUID | None
    payload: dict[str, Any]
