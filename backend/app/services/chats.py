import uuid
from typing import Literal, cast

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.chat import Chat, ChatMember
from app.db.models.user import User
from app.schemas.chats import ChatMemberRead


class ChatNotFound(Exception):
    """Raised when a chat is missing or not visible to the current user."""


class ChatPermissionDenied(Exception):
    """Raised when the user lacks the requested chat role."""


class ChatConflict(Exception):
    """Raised when a chat operation conflicts with current state."""


async def _active_users_exist(session: AsyncSession, user_ids: set[uuid.UUID]) -> bool:
    if not user_ids:
        return True
    result = await session.execute(
        select(func.count(User.id)).where(User.id.in_(user_ids), User.is_active.is_(True))
    )
    return result.scalar_one() == len(user_ids)


async def create_or_get_direct_chat(
    session: AsyncSession, current_user_id: uuid.UUID, other_user_id: uuid.UUID
) -> Chat:
    if current_user_id == other_user_id:
        raise ChatConflict("A direct chat requires two different users")
    if not await _active_users_exist(session, {current_user_id, other_user_id}):
        raise ChatNotFound

    low_id, high_id = sorted((current_user_id, other_user_id), key=lambda value: value.int)
    existing = await session.scalar(
        select(Chat).where(
            Chat.type == "direct",
            Chat.direct_user_low_id == low_id,
            Chat.direct_user_high_id == high_id,
        )
    )
    if existing is not None:
        return existing

    chat = Chat(
        type="direct",
        title=None,
        created_by=current_user_id,
        direct_user_low_id=low_id,
        direct_user_high_id=high_id,
    )
    session.add(chat)
    try:
        await session.flush()
        session.add_all(
            [
                ChatMember(chat_id=chat.id, user_id=low_id),
                ChatMember(chat_id=chat.id, user_id=high_id),
            ]
        )
        await session.commit()
    except IntegrityError:
        await session.rollback()
        existing = await session.scalar(
            select(Chat).where(
                Chat.type == "direct",
                Chat.direct_user_low_id == low_id,
                Chat.direct_user_high_id == high_id,
            )
        )
        if existing is not None:
            return existing
        raise ChatConflict("Unable to create direct chat") from None
    await session.refresh(chat)
    return chat


async def create_group_chat(
    session: AsyncSession,
    creator_id: uuid.UUID,
    title: str,
    requested_member_ids: list[uuid.UUID],
) -> Chat:
    member_ids = set(requested_member_ids)
    member_ids.add(creator_id)
    if len(member_ids) < 2:
        raise ChatConflict("A group must have at least two members")
    if not await _active_users_exist(session, member_ids):
        raise ChatNotFound

    chat = Chat(type="group", title=title, created_by=creator_id)
    session.add(chat)
    await session.flush()
    session.add_all(
        ChatMember(
            chat_id=chat.id,
            user_id=user_id,
            role="admin" if user_id == creator_id else "member",
        )
        for user_id in member_ids
    )
    await session.commit()
    await session.refresh(chat)
    return chat


async def _require_member(
    session: AsyncSession, chat_id: uuid.UUID, user_id: uuid.UUID
) -> ChatMember:
    member = await session.get(ChatMember, (chat_id, user_id))
    if member is None:
        raise ChatNotFound
    return member


async def set_chat_muted(
    session: AsyncSession, chat_id: uuid.UUID, user_id: uuid.UUID, muted: bool
) -> ChatMember:
    member = await _require_member(session, chat_id, user_id)
    member.muted = muted
    await session.commit()
    await session.refresh(member)
    return member


async def get_chat_for_member(
    session: AsyncSession, chat_id: uuid.UUID, user_id: uuid.UUID
) -> Chat:
    await _require_member(session, chat_id, user_id)
    chat = await session.get(Chat, chat_id)
    if chat is None:
        raise ChatNotFound
    return chat


async def list_user_chats(
    session: AsyncSession, user_id: uuid.UUID, limit: int, offset: int
) -> tuple[list[Chat], bool]:
    chats = list(
        (
            await session.scalars(
                select(Chat)
                .join(ChatMember, ChatMember.chat_id == Chat.id)
                .where(ChatMember.user_id == user_id)
                .order_by(
                    func.coalesce(Chat.last_message_at, Chat.created_at).desc(), Chat.id.desc()
                )
                .limit(limit + 1)
                .offset(offset)
            )
        ).all()
    )
    return chats[:limit], len(chats) > limit


async def list_chat_members(
    session: AsyncSession, chat_id: uuid.UUID, requester_id: uuid.UUID
) -> list[ChatMemberRead]:
    await _require_member(session, chat_id, requester_id)
    rows = await session.execute(
        select(ChatMember, User)
        .join(User, User.id == ChatMember.user_id)
        .where(ChatMember.chat_id == chat_id)
        .order_by(ChatMember.joined_at.asc(), User.username.asc())
    )
    return [
        ChatMemberRead(
            user_id=member.user_id,
            username=user.username,
            display_name=user.display_name,
            role=cast(Literal["admin", "member"], member.role),
            joined_at=member.joined_at,
            muted=member.muted,
        )
        for member, user in rows
    ]


async def list_chat_member_ids(
    session: AsyncSession, chat_id: uuid.UUID, requester_id: uuid.UUID
) -> list[uuid.UUID]:
    await _require_member(session, chat_id, requester_id)
    result = await session.scalars(select(ChatMember.user_id).where(ChatMember.chat_id == chat_id))
    return list(result.all())


async def add_group_member(
    session: AsyncSession,
    chat_id: uuid.UUID,
    requester_id: uuid.UUID,
    new_user_id: uuid.UUID,
) -> ChatMember:
    requester = await _require_member(session, chat_id, requester_id)
    chat = await session.get(Chat, chat_id)
    if chat is None:
        raise ChatNotFound
    if chat.type != "group":
        raise ChatConflict("Members can only be added to group chats")
    if requester.role != "admin":
        raise ChatPermissionDenied
    if not await _active_users_exist(session, {new_user_id}):
        raise ChatNotFound
    if await session.get(ChatMember, (chat_id, new_user_id)) is not None:
        raise ChatConflict("User is already a member of this chat")
    member = ChatMember(chat_id=chat_id, user_id=new_user_id, role="member")
    session.add(member)
    await session.commit()
    await session.refresh(member)
    return member


async def remove_group_member(
    session: AsyncSession,
    chat_id: uuid.UUID,
    requester_id: uuid.UUID,
    target_user_id: uuid.UUID,
) -> None:
    requester = await _require_member(session, chat_id, requester_id)
    chat = await session.get(Chat, chat_id)
    if chat is None:
        raise ChatNotFound
    if chat.type != "group":
        raise ChatConflict("Members can only be removed from group chats")
    if requester.role != "admin":
        raise ChatPermissionDenied
    target = await session.get(ChatMember, (chat_id, target_user_id))
    if target is None:
        raise ChatNotFound
    if target.role == "admin":
        admins = await session.scalar(
            select(func.count(ChatMember.user_id)).where(
                ChatMember.chat_id == chat_id, ChatMember.role == "admin"
            )
        )
        if (admins or 0) <= 1:
            raise ChatConflict("A group must keep at least one administrator")
    await session.delete(target)
    await session.commit()
