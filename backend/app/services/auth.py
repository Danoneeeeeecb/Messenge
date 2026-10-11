import uuid

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import create_access_token, hash_password, verify_password
from app.db.models.user import User
from app.schemas.users import LoginRequest, TokenRead, UserCreate


class RegistrationConflict(Exception):
    """Raised when a username or email address is already registered."""


class InvalidCredentials(Exception):
    """Raised when the supplied login details cannot authenticate a user."""


_DUMMY_PASSWORD_HASH = hash_password("login-timing-equalization-password")


async def register_user(session: AsyncSession, payload: UserCreate) -> User:
    user = User(
        username=payload.username,
        email=str(payload.email),
        password_hash=hash_password(payload.password),
        display_name=payload.display_name,
    )
    session.add(user)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise RegistrationConflict from exc
    await session.refresh(user)
    return user


async def authenticate_user(session: AsyncSession, payload: LoginRequest) -> TokenRead:
    result = await session.execute(
        select(User).where(
            or_(User.username == payload.identifier, User.email == payload.identifier)
        )
    )
    user = result.scalar_one_or_none()
    candidate_hash = user.password_hash if user is not None else _DUMMY_PASSWORD_HASH
    password_matches = verify_password(payload.password, candidate_hash)
    if user is None or not user.is_active or not password_matches:
        raise InvalidCredentials
    return TokenRead(
        access_token=create_access_token(user.id),
        expires_in=get_settings().access_token_expire_minutes * 60,
    )


async def get_active_user(session: AsyncSession, user_id: uuid.UUID) -> User | None:
    result = await session.execute(select(User).where(User.id == user_id, User.is_active.is_(True)))
    return result.scalar_one_or_none()
