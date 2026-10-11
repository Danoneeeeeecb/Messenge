import uuid
from pathlib import Path
from urllib.parse import unquote

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models.message import Message
from app.db.models.message_attachment import MessageAttachment
from app.db.models.user import User
from app.db.session import get_session
from app.dependencies.auth import get_current_user
from app.services.chats import ChatNotFound, list_chat_member_ids

router = APIRouter(tags=["attachments"])
settings = get_settings()


class AttachmentUploadRead(BaseModel):
    id: uuid.UUID
    filename: str
    content_type: str
    size: int
    download_url: str


@router.post(
    "/chats/{chat_id}/attachments",
    response_model=AttachmentUploadRead,
    status_code=status.HTTP_201_CREATED,
)
async def upload_attachment(
    chat_id: uuid.UUID,
    request: Request,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> AttachmentUploadRead:
    try:
        await list_chat_member_ids(session, chat_id, current_user.id)
    except ChatNotFound:
        raise HTTPException(
            status_code=404,
            detail={"code": "CHAT_NOT_FOUND", "message": "Chat not found"},
        ) from None

    declared_size = request.headers.get("content-length")
    size_exceeds_limit = False
    if declared_size is not None:
        try:
            size_exceeds_limit = int(declared_size) > settings.attachment_max_size_bytes
        except ValueError:
            size_exceeds_limit = True
    if size_exceeds_limit:
        raise HTTPException(
            status_code=413,
            detail={"code": "ATTACHMENT_TOO_LARGE", "message": "File exceeds the size limit"},
        )
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > settings.attachment_max_size_bytes:
            raise HTTPException(
                status_code=413,
                detail={
                    "code": "ATTACHMENT_TOO_LARGE",
                    "message": "File exceeds the size limit",
                },
            )
    if not data:
        raise HTTPException(
            status_code=422,
            detail={"code": "EMPTY_ATTACHMENT", "message": "File is empty"},
        )

    raw_filename = unquote(request.headers.get("x-file-name", ""))
    filename = Path(raw_filename.replace("\\", "/")).name.strip()
    if not filename or len(filename) > 255 or any(ord(char) < 32 for char in filename):
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_FILENAME", "message": "File name is invalid"},
        )
    content_type = request.headers.get("content-type", "application/octet-stream")[:255]
    attachment_id = uuid.uuid4()
    storage_name = f"{attachment_id.hex}.bin"
    storage_dir = Path(settings.attachment_storage_path).resolve()
    storage_dir.mkdir(parents=True, exist_ok=True)
    file_path = storage_dir / storage_name
    file_path.write_bytes(data)
    attachment = MessageAttachment(
        id=attachment_id,
        chat_id=chat_id,
        uploaded_by=current_user.id,
        filename=filename,
        content_type=content_type,
        size=len(data),
        storage_name=storage_name,
    )
    session.add(attachment)
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        file_path.unlink(missing_ok=True)
        raise
    return AttachmentUploadRead(
        id=attachment_id,
        filename=filename,
        content_type=content_type,
        size=len(data),
        download_url=f"{settings.api_v1_prefix}/attachments/{attachment_id}",
    )


@router.get("/attachments/{attachment_id}")
async def download_attachment(
    attachment_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> FileResponse:
    attachment = await session.get(MessageAttachment, attachment_id)
    if attachment is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "ATTACHMENT_NOT_FOUND", "message": "Attachment not found"},
        )
    try:
        members = await list_chat_member_ids(session, attachment.chat_id, current_user.id)
    except ChatNotFound:
        members = []
    if attachment.message_id is not None:
        message = await session.get(Message, attachment.message_id)
        if message is None or message.deleted_at is not None:
            members = []
    if not members or (attachment.message_id is None and attachment.uploaded_by != current_user.id):
        raise HTTPException(
            status_code=404,
            detail={"code": "ATTACHMENT_NOT_FOUND", "message": "Attachment not found"},
        )
    path = Path(settings.attachment_storage_path).resolve() / attachment.storage_name
    if not path.is_file():
        raise HTTPException(
            status_code=404,
            detail={"code": "ATTACHMENT_NOT_FOUND", "message": "Attachment file is missing"},
        )
    return FileResponse(
        path,
        media_type=attachment.content_type,
        filename=attachment.filename,
        content_disposition_type="attachment",
    )
