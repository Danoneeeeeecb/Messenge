"""Create message reactions table.

Revision ID: 20261011_0004
Revises: 20261011_0003
Create Date: 2026-10-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261011_0004"
down_revision: str | None = "20261011_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "message_reactions",
        sa.Column("message_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("emoji", sa.String(length=16), nullable=False),
        sa.CheckConstraint(
            "length(emoji) BETWEEN 1 AND 16", name=op.f("ck_message_reactions_emoji_length")
        ),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint(
            "message_id", "user_id", "emoji", name=op.f("pk_message_reactions")
        ),
    )


def downgrade() -> None:
    op.drop_table("message_reactions")
