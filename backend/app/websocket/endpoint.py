import asyncio
import json
import logging
import uuid
from typing import Annotated

import jwt
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.core.security import decode_access_token
from app.db.session import get_session_factory
from app.schemas.messages import MessageCreate, MessageUpdate
from app.schemas.websocket import (
    AuthenticatePayload,
    ChatReadPayload,
    ClientEvent,
    MessageDeletePayload,
    MessageEditPayload,
    MessageSendPayload,
    ReactionSetPayload,
)
from app.services.auth import get_active_user
from app.services.chats import ChatNotFound, ChatPermissionDenied, list_chat_member_ids
from app.services.messages import (
    ALLOWED_REACTIONS,
    MessageConflict,
    create_message,
    delete_message,
    mark_chat_read,
    serialize_messages,
    set_message_reaction,
    update_message,
)
from app.websocket.manager import Connection, WebSocketManager

logger = logging.getLogger(__name__)
router = APIRouter()
settings = get_settings()
manager = WebSocketManager(
    max_connections_per_user=settings.max_websocket_connections_per_user,
    rate_count=settings.message_rate_limit_count,
    rate_window=settings.message_rate_limit_window_seconds,
)


async def _send_error(
    websocket: WebSocket,
    code: str,
    message: str,
    request_id: uuid.UUID | None = None,
) -> None:
    await websocket.send_json(
        {
            "type": "error",
            "request_id": str(request_id) if request_id else None,
            "payload": {"code": code, "message": message},
        }
    )


async def _read_event(websocket: WebSocket, raw: str) -> ClientEvent | None:
    if len(raw.encode("utf-8")) > settings.websocket_max_message_bytes:
        await websocket.close(code=1009, reason="Event too large")
        return None
    try:
        return ClientEvent.model_validate(json.loads(raw))
    except (json.JSONDecodeError, ValidationError, TypeError):
        await _send_error(websocket, "INVALID_EVENT", "Event envelope is invalid")
        return None


@router.websocket("/api/v1/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    session_factory: Annotated[async_sessionmaker[AsyncSession], Depends(get_session_factory)],
) -> None:
    origin = websocket.headers.get("origin")
    if origin and origin not in settings.cors_origin_list:
        await websocket.close(code=4403, reason="Origin not allowed")
        return

    await websocket.accept()
    connection: Connection | None = None
    try:
        try:
            raw_auth_event = await asyncio.wait_for(websocket.receive_text(), timeout=10)
        except TimeoutError:
            await websocket.close(code=4408, reason="Authentication timed out")
            return
        auth_event = await _read_event(websocket, raw_auth_event)
        if auth_event is None:
            await websocket.close(code=4400, reason="Invalid authentication event")
            return
        if auth_event.type != "auth.authenticate":
            await websocket.close(code=4401, reason="Authentication required")
            return
        try:
            auth_payload = AuthenticatePayload.model_validate(auth_event.payload)
            user_id = decode_access_token(auth_payload.access_token)
            async with session_factory() as session:
                user = await get_active_user(session, user_id)
        except (ValidationError, jwt.InvalidTokenError, ValueError, TypeError, KeyError):
            user = None
        if user is None:
            await websocket.close(code=4401, reason="Invalid access token")
            return

        authenticated_user_id = user.id
        connection = await manager.register(websocket, authenticated_user_id)
        if connection is None:
            await websocket.close(code=4409, reason="Too many active connections")
            return
        await manager.send(
            connection,
            {
                "type": "connection.ready",
                "request_id": str(auth_event.request_id),
                "payload": {"user_id": str(authenticated_user_id)},
            },
        )

        while True:
            raw_event = await websocket.receive_text()
            event = await _read_event(websocket, raw_event)
            if event is None:
                continue
            if event.type == "chat.read":
                try:
                    read_payload = ChatReadPayload.model_validate(event.payload)
                except ValidationError:
                    await _send_error(
                        websocket,
                        "INVALID_READ_STATE",
                        "Read state payload is invalid",
                        event.request_id,
                    )
                    continue
                try:
                    async with session_factory() as session:
                        changed = await mark_chat_read(
                            session,
                            read_payload.chat_id,
                            read_payload.message_id,
                            authenticated_user_id,
                        )
                        if not changed:
                            continue
                        recipients = await list_chat_member_ids(
                            session, read_payload.chat_id, authenticated_user_id
                        )
                    await manager.broadcast(
                        recipients,
                        {
                            "type": "chat.read.updated",
                            "request_id": str(event.request_id),
                            "payload": {
                                "chat_id": str(read_payload.chat_id),
                                "message_id": str(read_payload.message_id),
                                "user_id": str(authenticated_user_id),
                            },
                        },
                    )
                except ChatNotFound:
                    await _send_error(
                        websocket,
                        "CHAT_ACCESS_DENIED",
                        "You do not have access to this chat or message",
                        event.request_id,
                    )
                continue

            if event.type in {"message.edit", "message.delete"}:
                try:
                    if event.type == "message.edit":
                        edit_payload = MessageEditPayload.model_validate(event.payload)
                    else:
                        delete_payload = MessageDeletePayload.model_validate(event.payload)
                except ValidationError:
                    await _send_error(
                        websocket,
                        "INVALID_MESSAGE",
                        "Message update payload is invalid",
                        event.request_id,
                    )
                    continue
                if not await manager.allow_message(authenticated_user_id):
                    await _send_error(
                        websocket,
                        "MESSAGE_RATE_LIMITED",
                        "Action rate limit exceeded",
                        event.request_id,
                    )
                    continue
                try:
                    async with session_factory() as session:
                        if event.type == "message.edit":
                            updated_message = await update_message(
                                session,
                                edit_payload.message_id,
                                authenticated_user_id,
                                MessageUpdate(content=edit_payload.content),
                            )
                        else:
                            updated_message = await delete_message(
                                session, delete_payload.message_id, authenticated_user_id
                            )
                        serialized = (
                            await serialize_messages(
                                session, [updated_message], authenticated_user_id
                            )
                        )[0].model_dump(mode="json")
                        recipients = await list_chat_member_ids(
                            session, updated_message.chat_id, authenticated_user_id
                        )
                    await manager.broadcast(
                        recipients,
                        {
                            "type": "message.updated",
                            "request_id": str(event.request_id),
                            "payload": {"message": serialized},
                        },
                    )
                except ChatNotFound:
                    await _send_error(
                        websocket, "MESSAGE_NOT_FOUND", "Message is not available", event.request_id
                    )
                except ChatPermissionDenied:
                    await _send_error(
                        websocket,
                        "MESSAGE_EDIT_FORBIDDEN",
                        "Only the message author can change it",
                        event.request_id,
                    )
                except Exception as exc:
                    logger.error("WebSocket message update failed (%s)", type(exc).__name__)
                    await _send_error(
                        websocket,
                        "INTERNAL_ERROR",
                        "Message could not be updated",
                        event.request_id,
                    )
                continue

            if event.type == "reaction.set":
                try:
                    reaction_payload = ReactionSetPayload.model_validate(event.payload)
                except ValidationError:
                    await _send_error(
                        websocket,
                        "INVALID_REACTION",
                        "Reaction payload is invalid",
                        event.request_id,
                    )
                    continue
                if reaction_payload.emoji not in ALLOWED_REACTIONS:
                    await _send_error(
                        websocket,
                        "INVALID_REACTION",
                        "Reaction emoji is not supported",
                        event.request_id,
                    )
                    continue
                if not await manager.allow_message(authenticated_user_id):
                    await _send_error(
                        websocket,
                        "MESSAGE_RATE_LIMITED",
                        "Action rate limit exceeded",
                        event.request_id,
                    )
                    continue
                try:
                    async with session_factory() as session:
                        count = await set_message_reaction(
                            session,
                            reaction_payload.chat_id,
                            reaction_payload.message_id,
                            authenticated_user_id,
                            reaction_payload.emoji,
                            reaction_payload.active,
                        )
                        recipients = await list_chat_member_ids(
                            session, reaction_payload.chat_id, authenticated_user_id
                        )
                    await manager.broadcast(
                        recipients,
                        {
                            "type": "reaction.updated",
                            "request_id": str(event.request_id),
                            "payload": {
                                "chat_id": str(reaction_payload.chat_id),
                                "message_id": str(reaction_payload.message_id),
                                "user_id": str(authenticated_user_id),
                                "emoji": reaction_payload.emoji,
                                "active": reaction_payload.active,
                                "count": count,
                            },
                        },
                    )
                except ChatNotFound:
                    await _send_error(
                        websocket,
                        "CHAT_ACCESS_DENIED",
                        "You do not have access to this chat or message",
                        event.request_id,
                    )
                except Exception as exc:
                    logger.error("WebSocket reaction processing failed (%s)", type(exc).__name__)
                    await _send_error(
                        websocket,
                        "INTERNAL_ERROR",
                        "Reaction could not be processed",
                        event.request_id,
                    )
                continue

            if event.type != "message.send":
                await _send_error(
                    websocket,
                    "UNKNOWN_EVENT",
                    "Event type is not supported",
                    event.request_id,
                )
                continue
            try:
                payload = MessageSendPayload.model_validate(event.payload)
            except ValidationError:
                await _send_error(
                    websocket,
                    "INVALID_MESSAGE",
                    "Message payload is invalid",
                    event.request_id,
                )
                continue
            if len(payload.content) > settings.message_max_length or (
                not payload.content.strip() and not payload.attachment_ids
            ):
                await _send_error(
                    websocket,
                    "INVALID_MESSAGE",
                    "Message content is blank or exceeds the configured limit",
                    event.request_id,
                )
                continue
            if not await manager.allow_message(authenticated_user_id):
                await _send_error(
                    websocket,
                    "MESSAGE_RATE_LIMITED",
                    "Message rate limit exceeded",
                    event.request_id,
                )
                continue

            try:
                async with session_factory() as session:
                    message = await create_message(
                        session,
                        authenticated_user_id,
                        MessageCreate(
                            chat_id=payload.chat_id,
                            client_message_id=payload.client_message_id,
                            content=payload.content,
                            reply_to_message_id=payload.reply_to_message_id,
                            attachment_ids=payload.attachment_ids,
                        ),
                    )
                    serialized_message = (
                        await serialize_messages(session, [message], authenticated_user_id)
                    )[0].model_dump(mode="json")
                    recipients = await list_chat_member_ids(
                        session, message.chat_id, authenticated_user_id
                    )
                ack = {
                    "type": "message.ack",
                    "request_id": str(event.request_id),
                    "payload": {"message": serialized_message},
                }
                try:
                    await manager.send(connection, ack)
                except (WebSocketDisconnect, RuntimeError):
                    pass
                await manager.broadcast(
                    recipients,
                    {
                        "type": "message.new",
                        "request_id": str(event.request_id),
                        "payload": {"message": serialized_message},
                    },
                )
            except ChatNotFound:
                await _send_error(
                    websocket,
                    "CHAT_ACCESS_DENIED",
                    "You do not have access to this chat",
                    event.request_id,
                )
            except MessageConflict:
                await _send_error(
                    websocket,
                    "MESSAGE_ID_CONFLICT",
                    "Client message id was already used with different data",
                    event.request_id,
                )
            except Exception as exc:
                logger.error("WebSocket message processing failed (%s)", type(exc).__name__)
                await _send_error(
                    websocket,
                    "INTERNAL_ERROR",
                    "Message could not be processed",
                    event.request_id,
                )
                await websocket.close(code=1011, reason="Message processing failed")
                return
    except WebSocketDisconnect:
        return
    finally:
        if connection is not None:
            await manager.unregister(connection)
