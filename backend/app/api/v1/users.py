from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.rate_limit import SlidingWindowRateLimiter
from app.db.models.user import User
from app.db.session import get_session
from app.dependencies.auth import get_current_user
from app.schemas.user_search import UserSearchItem
from app.schemas.users import UserRead
from app.services.users import search_active_users

router = APIRouter(prefix="/users", tags=["users"])
settings = get_settings()
search_limiter = SlidingWindowRateLimiter(
    settings.user_search_rate_limit_count,
    settings.user_search_rate_limit_window_seconds,
)


@router.get("/me", response_model=UserRead)
async def current_user(user: Annotated[User, Depends(get_current_user)]) -> User:
    return user


@router.get("/search", response_model=list[UserSearchItem])
async def search_users(
    q: Annotated[str, Query(min_length=1, max_length=64)],
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=20)] = 20,
) -> list[UserSearchItem]:
    query = q.strip()
    if not query:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "INVALID_REQUEST", "message": "Search query cannot be blank"},
        )
    if not await search_limiter.allow(current_user.id):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"code": "SEARCH_RATE_LIMITED", "message": "User search rate limit exceeded"},
        )
    return await search_active_users(session, current_user.id, query, limit)
