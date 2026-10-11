import uuid

from pydantic import BaseModel


class UserSearchItem(BaseModel):
    id: uuid.UUID
    username: str
    display_name: str
