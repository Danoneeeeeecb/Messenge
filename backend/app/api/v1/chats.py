import uuid
from typing import Annotated, NoReturn, cast

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.chat import ChatMember
from app.db.models.message import Message
from app.db.models.user import User
from app.db.session import get_session
from app.dependencies.auth import get_current_user
from app.schemas.chats import (
    ChatListRead,
    ChatMemberAdd,
    ChatMemberRead,
    ChatPeerRead,
    ChatPreferencesRead,
    ChatPreferencesUpdate,
    ChatRead,
    DirectChatCreate,
    GroupChatCreate,
)
from app.services.chats import (
    ChatConflict,
    ChatNotFound,
    ChatPermissionDenied,
    add_group_member,
    create_group_chat,
    create_or_get_direct_chat,
    get_chat_for_member,
    list_chat_members,
    list_user_chats,
    remove_group_member,
    set_chat_muted,
)

router = APIRouter(prefix="/chats", tags=["chats"])


def _raise_chat_error(exc: Exception) -> NoReturn:
    if isinstance(exc, ChatNotFound):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "CHAT_OR_USER_NOT_FOUND", "message": "Chat or user not found"},
        ) from None
    if isinstance(exc, ChatPermissionDenied):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "CHAT_ADMIN_REQUIRED", "message": "Chat administrator role required"},
        ) from None
    if isinstance(exc, ChatConflict):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "CHAT_CONFLICT", "message": str(exc)},
        ) from None
    raise exc


@router.get("", response_model=ChatListRead)
async def get_chats(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> ChatListRead:
    chats, has_more = await list_user_chats(session, current_user.id, limit, offset)
    muted_chat_ids = set(
        (
            await session.scalars(
                select(ChatMember.chat_id).where(
                    ChatMember.user_id == current_user.id, ChatMember.muted.is_(True)
                )
            )
        ).all()
    )
    direct_chat_ids = [chat.id for chat in chats if chat.type == "direct"]
    peers: dict[uuid.UUID, ChatPeerRead] = {}
    previews: dict[uuid.UUID, str] = {}
    if direct_chat_ids:
        peer_rows = await session.execute(
            select(ChatMember.chat_id, User.id, User.username, User.display_name)
            .join(User, User.id == ChatMember.user_id)
            .where(
                ChatMember.chat_id.in_(direct_chat_ids),
                ChatMember.user_id != current_user.id,
            )
        )
        peers = {
            chat_id: ChatPeerRead(id=user_id, username=username, display_name=display_name)
            for chat_id, user_id, username, display_name in peer_rows
        }
    chat_ids = [chat.id for chat in chats]
    if chat_ids:
        ranked_messages = (
            select(
                Message.chat_id.label("chat_id"),
                Message.content.label("content"),
                func.row_number()
                .over(
                    partition_by=Message.chat_id,
                    order_by=(Message.created_at.desc(), Message.id.desc()),
                )
                .label("position"),
            )
            .where(Message.chat_id.in_(chat_ids))
            .subquery()
        )
        message_rows = await session.execute(
            select(ranked_messages.c.chat_id, ranked_messages.c.content).where(
                ranked_messages.c.position == 1
            )
        )
        previews = {
            cast(uuid.UUID, chat_id): cast(str, content) for chat_id, content in message_rows
        }
    return ChatListRead(
        items=[
            ChatRead.model_validate(chat).model_copy(
                update={
                    "peer": peers.get(chat.id),
                    "last_message": previews.get(chat.id),
                    "muted": chat.id in muted_chat_ids,
                }
            )
            for chat in chats
        ],
        next_offset=offset + limit if has_more else None,
    )


@router.post("/direct", response_model=ChatRead)
async def create_direct(
    payload: DirectChatCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ChatRead:
    try:
        chat = await create_or_get_direct_chat(session, current_user.id, payload.user_id)
        return ChatRead.model_validate(chat)
    except (ChatNotFound, ChatConflict) as exc:
        _raise_chat_error(exc)


@router.post("/group", response_model=ChatRead, status_code=status.HTTP_201_CREATED)
async def create_group(
    payload: GroupChatCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ChatRead:
    try:
        chat = await create_group_chat(session, current_user.id, payload.title, payload.member_ids)
        return ChatRead.model_validate(chat)
    except (ChatNotFound, ChatConflict) as exc:
        _raise_chat_error(exc)


@router.get("/{chat_id}", response_model=ChatRead)
async def get_chat(
    chat_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ChatRead:
    try:
        chat = await get_chat_for_member(session, chat_id, current_user.id)
        return ChatRead.model_validate(chat)
    except ChatNotFound as exc:
        _raise_chat_error(exc)


@router.patch("/{chat_id}/preferences", response_model=ChatPreferencesRead)
async def update_chat_preferences(
    chat_id: uuid.UUID,
    payload: ChatPreferencesUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ChatPreferencesRead:
    try:
        member = await set_chat_muted(session, chat_id, current_user.id, payload.muted)
        return ChatPreferencesRead(muted=member.muted)
    except ChatNotFound as exc:
        _raise_chat_error(exc)


@router.get("/{chat_id}/members", response_model=list[ChatMemberRead])
async def get_members(
    chat_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[ChatMemberRead]:
    try:
        return await list_chat_members(session, chat_id, current_user.id)
    except ChatNotFound as exc:
        _raise_chat_error(exc)


@router.post(
    "/{chat_id}/members",
    response_model=ChatMemberRead,
    status_code=status.HTTP_201_CREATED,
)
async def add_member(
    chat_id: uuid.UUID,
    payload: ChatMemberAdd,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ChatMemberRead:
    try:
        member = await add_group_member(session, chat_id, current_user.id, payload.user_id)
        members = await list_chat_members(session, chat_id, current_user.id)
        return next(item for item in members if item.user_id == member.user_id)
    except (ChatNotFound, ChatPermissionDenied, ChatConflict) as exc:
        _raise_chat_error(exc)


@router.delete("/{chat_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_member(
    chat_id: uuid.UUID,
    user_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    try:
        await remove_group_member(session, chat_id, current_user.id, user_id)
    except (ChatNotFound, ChatPermissionDenied, ChatConflict) as exc:
        _raise_chat_error(exc)
