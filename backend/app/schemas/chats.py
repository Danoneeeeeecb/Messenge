import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DirectChatCreate(BaseModel):
    user_id: uuid.UUID


class GroupChatCreate(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    member_ids: list[uuid.UUID] = Field(min_length=1, max_length=99)

    @field_validator("title")
    @classmethod
    def trim_title(cls, value: str) -> str:
        title = value.strip()
        if not title:
            raise ValueError("Group title cannot be blank")
        return title

    @field_validator("member_ids")
    @classmethod
    def require_distinct_members(cls, value: list[uuid.UUID]) -> list[uuid.UUID]:
        if len(value) != len(set(value)):
            raise ValueError("Group member ids must be unique")
        return value


class ChatMemberAdd(BaseModel):
    user_id: uuid.UUID


class ChatPeerRead(BaseModel):
    id: uuid.UUID
    username: str
    display_name: str


class ChatRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    type: Literal["direct", "group"]
    title: str | None
    created_by: uuid.UUID
    created_at: datetime
    updated_at: datetime
    last_message_at: datetime | None
    last_message: str | None = None
    peer: ChatPeerRead | None = None
    muted: bool = False


class ChatMemberRead(BaseModel):
    user_id: uuid.UUID
    username: str
    display_name: str
    role: Literal["admin", "member"]
    joined_at: datetime
    muted: bool = False


class ChatPreferencesUpdate(BaseModel):
    muted: bool


class ChatPreferencesRead(BaseModel):
    muted: bool


class ChatListRead(BaseModel):
    items: list[ChatRead]
    next_offset: int | None = None
