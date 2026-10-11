import uuid

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.user import User
from app.schemas.user_search import UserSearchItem


async def search_active_users(
    session: AsyncSession, current_user_id: uuid.UUID, query: str, limit: int
) -> list[UserSearchItem]:
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    pattern = f"%{escaped}%"
    users = await session.scalars(
        select(User)
        .where(
            User.is_active.is_(True),
            User.id != current_user_id,
            or_(
                User.username.ilike(pattern, escape="\\"),
                User.display_name.ilike(pattern, escape="\\"),
            ),
        )
        .order_by(User.username.asc(), User.id.asc())
        .limit(limit)
    )
    return [
        UserSearchItem(id=user.id, username=user.username, display_name=user.display_name)
        for user in users
    ]
