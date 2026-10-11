import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.user import User
from app.db.session import get_session
from app.dependencies.auth import get_current_user
from app.schemas.messages import MessagePage
from app.services.chats import ChatNotFound
from app.services.messages import (
    InvalidMessageCursor,
    get_message_history,
    search_chat_messages,
    serialize_messages,
)

router = APIRouter(prefix="/chats/{chat_id}/messages", tags=["messages"])


@router.get("", response_model=MessagePage)
async def history(
    chat_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: int = Query(default=50, ge=1, le=100),
    before: str | None = Query(default=None, max_length=512),
) -> MessagePage:
    try:
        messages, cursor = await get_message_history(
            session, chat_id, current_user.id, limit, before
        )
    except ChatNotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "CHAT_NOT_FOUND", "message": "Chat not found"},
        ) from None
    except InvalidMessageCursor:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "INVALID_CURSOR", "message": "Message cursor is invalid"},
        ) from None
    return MessagePage(
        items=await serialize_messages(session, messages, current_user.id),
        next_cursor=cursor,
    )


@router.get("/search", response_model=MessagePage)
async def search(
    chat_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    q: str = Query(min_length=1, max_length=200),
    limit: int = Query(default=50, ge=1, le=100),
) -> MessagePage:
    query = q.strip()
    if not query:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "INVALID_REQUEST", "message": "Search query cannot be blank"},
        )
    try:
        messages = await search_chat_messages(session, chat_id, current_user.id, query, limit)
    except ChatNotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "CHAT_NOT_FOUND", "message": "Chat not found"},
        ) from None
    return MessagePage(
        items=await serialize_messages(session, messages, current_user.id),
        next_cursor=None,
    )
