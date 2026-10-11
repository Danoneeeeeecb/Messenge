import base64
import json
import re
import uuid
from datetime import UTC, datetime

from sqlalchemy import and_, case, delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.chat import Chat, ChatMember
from app.db.models.message import Message
from app.db.models.message_attachment import MessageAttachment
from app.db.models.message_mention import MessageMention
from app.db.models.message_reaction import MessageReaction
from app.db.models.user import User
from app.schemas.messages import (
    MessageAttachmentRead,
    MessageCreate,
    MessageMentionRead,
    MessageReactionSummary,
    MessageRead,
    MessageReplyRead,
    MessageUpdate,
)
from app.services.chats import ChatNotFound, ChatPermissionDenied


class MessageConflict(Exception):
    """Raised when a client message id is reused with different content."""


class InvalidMessageCursor(Exception):
    """Raised when a history cursor is malformed."""


ALLOWED_REACTIONS = frozenset({"👍", "❤️", "😂", "😮", "😢", "🎉", "🔥", "🙏"})
MENTION_PATTERN = re.compile(r"(?<![\w@])@([A-Za-z0-9_]{3,32})")


def encode_message_cursor(message: Message) -> str:
    created_at = message.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    payload = json.dumps(
        {"created_at": created_at.isoformat(), "id": str(message.id)},
        separators=(",", ":"),
    ).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def decode_message_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    if len(cursor) > 512:
        raise InvalidMessageCursor
    try:
        padding = "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(cursor + padding))
        created_at = datetime.fromisoformat(payload["created_at"])
        if created_at.tzinfo is None:
            raise ValueError("Cursor timestamp must include a timezone")
        message_id = uuid.UUID(payload["id"])
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        raise InvalidMessageCursor from None
    return created_at, message_id


async def _require_chat_member(
    session: AsyncSession, chat_id: uuid.UUID, user_id: uuid.UUID
) -> ChatMember:
    member = await session.get(ChatMember, (chat_id, user_id))
    if member is None:
        raise ChatNotFound
    return member


async def create_message(
    session: AsyncSession, sender_id: uuid.UUID, payload: MessageCreate
) -> Message:
    await _require_chat_member(session, payload.chat_id, sender_id)
    existing = await session.scalar(
        select(Message).where(
            Message.sender_id == sender_id,
            Message.client_message_id == payload.client_message_id,
        )
    )
    if existing is not None:
        if (
            existing.chat_id != payload.chat_id
            or existing.reply_to_message_id != payload.reply_to_message_id
        ):
            raise MessageConflict
        existing_attachment_ids = set(
            (
                await session.scalars(
                    select(MessageAttachment.id).where(MessageAttachment.message_id == existing.id)
                )
            ).all()
        )
        matches = existing_attachment_ids == set(payload.attachment_ids)
        if payload.content.strip():
            matches = matches and existing.content == payload.content
        if matches:
            return existing
        raise MessageConflict

    reply_to: Message | None = None
    if payload.reply_to_message_id is not None:
        reply_to = await session.scalar(
            select(Message).where(
                Message.id == payload.reply_to_message_id,
                Message.chat_id == payload.chat_id,
            )
        )
        if reply_to is None:
            raise ChatNotFound

    attachments: list[MessageAttachment] = []
    if payload.attachment_ids:
        attachments = list(
            (
                await session.scalars(
                    select(MessageAttachment).where(
                        MessageAttachment.id.in_(payload.attachment_ids),
                        MessageAttachment.chat_id == payload.chat_id,
                        MessageAttachment.uploaded_by == sender_id,
                        MessageAttachment.message_id.is_(None),
                    )
                )
            ).all()
        )
        if len(attachments) != len(payload.attachment_ids):
            raise ChatNotFound

    content = payload.content
    if not content.strip():
        content = "📎 " + ", ".join(item.filename for item in attachments)
    message = Message(
        chat_id=payload.chat_id,
        sender_id=sender_id,
        client_message_id=payload.client_message_id,
        content=content,
        reply_to_message_id=payload.reply_to_message_id,
    )
    session.add(message)
    try:
        await session.flush()
        for attachment in attachments:
            attachment.message_id = message.id
        mention_names = {match.lower() for match in MENTION_PATTERN.findall(content)}
        if mention_names:
            mentioned_users = await session.scalars(
                select(User)
                .join(ChatMember, ChatMember.user_id == User.id)
                .where(
                    ChatMember.chat_id == payload.chat_id,
                    func.lower(User.username).in_(mention_names),
                )
            )
            session.add_all(
                MessageMention(message_id=message.id, user_id=mentioned.id)
                for mentioned in mentioned_users
            )
        await session.execute(
            update(Chat)
            .where(Chat.id == payload.chat_id)
            .values(
                last_message_at=case(
                    (Chat.last_message_at.is_(None), message.created_at),
                    (Chat.last_message_at < message.created_at, message.created_at),
                    else_=Chat.last_message_at,
                )
            )
        )
        await session.commit()
    except IntegrityError:
        await session.rollback()
        existing = await session.scalar(
            select(Message).where(
                Message.sender_id == sender_id,
                Message.client_message_id == payload.client_message_id,
            )
        )
        if (
            existing is not None
            and existing.chat_id == payload.chat_id
            and existing.content == content
        ):
            return existing
        raise MessageConflict from None
    await session.refresh(message)
    return message


async def update_message(
    session: AsyncSession, message_id: uuid.UUID, user_id: uuid.UUID, payload: MessageUpdate
) -> Message:
    message = await session.get(Message, message_id)
    if message is None:
        raise ChatNotFound
    await _require_chat_member(session, message.chat_id, user_id)
    if message.sender_id != user_id or message.deleted_at is not None:
        raise ChatPermissionDenied
    message.content = payload.content.strip()
    message.edited = True
    message.updated_at = datetime.now(UTC)
    await session.execute(delete(MessageMention).where(MessageMention.message_id == message.id))
    mention_names = {match.lower() for match in MENTION_PATTERN.findall(message.content)}
    if mention_names:
        mentioned_users = await session.scalars(
            select(User)
            .join(ChatMember, ChatMember.user_id == User.id)
            .where(
                ChatMember.chat_id == message.chat_id,
                func.lower(User.username).in_(mention_names),
            )
        )
        session.add_all(
            MessageMention(message_id=message.id, user_id=mentioned.id)
            for mentioned in mentioned_users
        )
    await session.commit()
    await session.refresh(message)
    return message


async def delete_message(
    session: AsyncSession, message_id: uuid.UUID, user_id: uuid.UUID
) -> Message:
    message = await session.get(Message, message_id)
    if message is None:
        raise ChatNotFound
    await _require_chat_member(session, message.chat_id, user_id)
    if message.sender_id != user_id or message.deleted_at is not None:
        raise ChatPermissionDenied
    message.content = "Сообщение удалено"
    message.deleted_at = datetime.now(UTC)
    message.updated_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(message)
    return message


async def mark_chat_read(
    session: AsyncSession, chat_id: uuid.UUID, message_id: uuid.UUID, user_id: uuid.UUID
) -> bool:
    member = await _require_chat_member(session, chat_id, user_id)
    target = await session.scalar(
        select(Message).where(Message.id == message_id, Message.chat_id == chat_id)
    )
    if target is None:
        raise ChatNotFound
    if member.last_read_message_id is not None:
        previous = await session.get(Message, member.last_read_message_id)
        if previous is not None and (previous.created_at, previous.id.int) >= (
            target.created_at,
            target.id.int,
        ):
            return False
    member.last_read_message_id = message_id
    await session.commit()
    return True


async def get_message_history(
    session: AsyncSession,
    chat_id: uuid.UUID,
    user_id: uuid.UUID,
    limit: int,
    before: str | None,
) -> tuple[list[Message], str | None]:
    await _require_chat_member(session, chat_id, user_id)
    statement = select(Message).where(Message.chat_id == chat_id)
    if before is not None:
        cursor_time, cursor_id = decode_message_cursor(before)
        statement = statement.where(
            or_(
                Message.created_at < cursor_time,
                and_(Message.created_at == cursor_time, Message.id < cursor_id),
            )
        )
    rows = list(
        (
            await session.scalars(
                statement.order_by(Message.created_at.desc(), Message.id.desc()).limit(limit + 1)
            )
        ).all()
    )
    has_more = len(rows) > limit
    page = list(reversed(rows[:limit]))
    next_cursor = encode_message_cursor(page[0]) if has_more and page else None
    return page, next_cursor


async def search_chat_messages(
    session: AsyncSession, chat_id: uuid.UUID, user_id: uuid.UUID, query: str, limit: int
) -> list[Message]:
    await _require_chat_member(session, chat_id, user_id)
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    result = await session.scalars(
        select(Message)
        .where(
            Message.chat_id == chat_id,
            Message.deleted_at.is_(None),
            Message.content.ilike(f"%{escaped}%", escape="\\"),
        )
        .order_by(Message.created_at.desc(), Message.id.desc())
        .limit(limit)
    )
    return list(reversed(result.all()))


async def get_message_reactions(
    session: AsyncSession, messages: list[Message], user_id: uuid.UUID
) -> dict[uuid.UUID, list[MessageReactionSummary]]:
    if not messages:
        return {}
    reacted_by_me = case((MessageReaction.user_id == user_id, 1), else_=0)
    rows = await session.execute(
        select(
            MessageReaction.message_id,
            MessageReaction.emoji,
            func.count().label("count"),
            func.max(reacted_by_me).label("reacted_by_me"),
        )
        .where(MessageReaction.message_id.in_([message.id for message in messages]))
        .group_by(MessageReaction.message_id, MessageReaction.emoji)
    )
    result: dict[uuid.UUID, list[MessageReactionSummary]] = {}
    for message_id, emoji, count, has_reacted in rows:
        result.setdefault(message_id, []).append(
            MessageReactionSummary(
                emoji=emoji,
                count=count,
                reacted_by_me=bool(has_reacted),
            )
        )
    return result


async def serialize_messages(
    session: AsyncSession, messages: list[Message], user_id: uuid.UUID
) -> list[MessageRead]:
    if not messages:
        return []
    message_ids = [message.id for message in messages]
    reactions = await get_message_reactions(session, messages, user_id)
    live_message_ids = [message.id for message in messages if message.deleted_at is None]
    attachment_rows = await session.scalars(
        select(MessageAttachment).where(MessageAttachment.message_id.in_(live_message_ids))
    )
    attachments: dict[uuid.UUID, list[MessageAttachmentRead]] = {}
    for attachment in attachment_rows:
        if attachment.message_id is None:
            continue
        attachments.setdefault(attachment.message_id, []).append(
            MessageAttachmentRead(
                id=attachment.id,
                filename=attachment.filename,
                content_type=attachment.content_type,
                size=attachment.size,
                download_url=f"/api/v1/attachments/{attachment.id}",
            )
        )
    mention_rows = await session.execute(
        select(MessageMention.message_id, User.id, User.username, User.display_name)
        .join(User, User.id == MessageMention.user_id)
        .where(MessageMention.message_id.in_(message_ids))
    )
    mentions: dict[uuid.UUID, list[MessageMentionRead]] = {}
    for message_id, mentioned_id, username, display_name in mention_rows:
        mentions.setdefault(message_id, []).append(
            MessageMentionRead(user_id=mentioned_id, username=username, display_name=display_name)
        )
    reply_ids = {message.reply_to_message_id for message in messages if message.reply_to_message_id}
    reply_rows = await session.scalars(select(Message).where(Message.id.in_(reply_ids)))
    replies = {
        reply.id: MessageReplyRead(
            id=reply.id,
            sender_id=reply.sender_id,
            content=reply.content,
            deleted_at=reply.deleted_at,
        )
        for reply in reply_rows
    }
    read_rows = await session.execute(
        select(ChatMember.chat_id, ChatMember.user_id, Message.created_at, Message.id)
        .join(Message, Message.id == ChatMember.last_read_message_id)
        .where(ChatMember.chat_id.in_({message.chat_id for message in messages}))
    )
    read_markers: dict[uuid.UUID, list[tuple[uuid.UUID, datetime, uuid.UUID]]] = {}
    for chat_id, reader_id, created_at, marker_id in read_rows:
        read_markers.setdefault(chat_id, []).append((reader_id, created_at, marker_id))

    output: list[MessageRead] = []
    for message in messages:
        readers = [
            reader_id
            for reader_id, read_at, read_id in read_markers.get(message.chat_id, [])
            if reader_id != message.sender_id
            and (read_at, read_id.int)
            >= (
                message.created_at,
                message.id.int,
            )
        ]
        output.append(
            MessageRead.model_validate(message).model_copy(
                update={
                    "reactions": reactions.get(message.id, []),
                    "attachments": attachments.get(message.id, []),
                    "mentions": mentions.get(message.id, []),
                    "reply_to": replies.get(message.reply_to_message_id)
                    if message.reply_to_message_id is not None
                    else None,
                    "read_by": readers,
                }
            )
        )
    return output


async def set_message_reaction(
    session: AsyncSession,
    chat_id: uuid.UUID,
    message_id: uuid.UUID,
    user_id: uuid.UUID,
    emoji: str,
    active: bool,
) -> int:
    if emoji not in ALLOWED_REACTIONS:
        raise ValueError("Reaction emoji is not supported")
    await _require_chat_member(session, chat_id, user_id)
    message_exists = await session.scalar(
        select(Message.id).where(Message.id == message_id, Message.chat_id == chat_id)
    )
    if message_exists is None:
        raise ChatNotFound

    reaction = await session.get(MessageReaction, (message_id, user_id, emoji))
    if active and reaction is None:
        session.add(MessageReaction(message_id=message_id, user_id=user_id, emoji=emoji))
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
    elif not active and reaction is not None:
        await session.delete(reaction)
        await session.commit()
    return int(
        await session.scalar(
            select(func.count())
            .select_from(MessageReaction)
            .where(MessageReaction.message_id == message_id, MessageReaction.emoji == emoji)
        )
        or 0
    )
