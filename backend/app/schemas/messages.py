import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class MessageCreate(BaseModel):
    chat_id: uuid.UUID
    client_message_id: uuid.UUID
    content: str = Field(max_length=10_000)
    reply_to_message_id: uuid.UUID | None = None
    attachment_ids: list[uuid.UUID] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def require_content_or_attachment(self) -> "MessageCreate":
        if not self.content.strip() and not self.attachment_ids:
            raise ValueError("Message cannot be blank")
        if len(self.attachment_ids) != len(set(self.attachment_ids)):
            raise ValueError("Attachment ids must be unique")
        return self


class MessageUpdate(BaseModel):
    content: str = Field(min_length=1, max_length=10_000)

    @field_validator("content")
    @classmethod
    def require_nonblank_content(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Message cannot be blank")
        return value


class MessageAttachmentRead(BaseModel):
    id: uuid.UUID
    filename: str
    content_type: str
    size: int
    download_url: str


class MessageMentionRead(BaseModel):
    user_id: uuid.UUID
    username: str
    display_name: str


class MessageReplyRead(BaseModel):
    id: uuid.UUID
    sender_id: uuid.UUID
    content: str
    deleted_at: datetime | None


class MessageReactionSummary(BaseModel):
    emoji: str
    count: int
    reacted_by_me: bool


class MessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    chat_id: uuid.UUID
    sender_id: uuid.UUID
    client_message_id: uuid.UUID
    content: str
    created_at: datetime
    updated_at: datetime | None
    edited: bool
    deleted_at: datetime | None = None
    reactions: list[MessageReactionSummary] = Field(default_factory=list)
    attachments: list[MessageAttachmentRead] = Field(default_factory=list)
    mentions: list[MessageMentionRead] = Field(default_factory=list)
    reply_to: MessageReplyRead | None = None
    read_by: list[uuid.UUID] = Field(default_factory=list)


class ChatReadUpdate(BaseModel):
    message_id: uuid.UUID


class MessagePage(BaseModel):
    items: list[MessageRead]
    next_cursor: str | None
