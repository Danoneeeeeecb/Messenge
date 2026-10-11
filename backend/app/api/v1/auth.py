from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.user import User
from app.db.session import get_session
from app.schemas.users import LoginRequest, TokenRead, UserCreate, UserRead
from app.services.auth import (
    InvalidCredentials,
    RegistrationConflict,
    authenticate_user,
    register_user,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def register(payload: UserCreate, session: AsyncSession = Depends(get_session)) -> User:
    try:
        return await register_user(session, payload)
    except RegistrationConflict:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "REGISTRATION_CONFLICT",
                "message": "Username or email is already registered",
            },
        ) from None


@router.post("/login", response_model=TokenRead)
async def login(payload: LoginRequest, session: AsyncSession = Depends(get_session)) -> TokenRead:
    try:
        return await authenticate_user(session, payload)
    except InvalidCredentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "INVALID_CREDENTIALS",
                "message": "Invalid username/email or password",
            },
            headers={"WWW-Authenticate": "Bearer"},
        ) from None
