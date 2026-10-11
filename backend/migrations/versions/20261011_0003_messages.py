"""Create messages table.

Revision ID: 20261011_0003
Revises: 20261011_0002
Create Date: 2026-10-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261011_0003"
down_revision: str | None = "20261011_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "messages",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("chat_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("sender_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("client_message_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("edited", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "length(trim(content)) > 0 AND length(content) <= 10000",
            name=op.f("ck_messages_content_length"),
        ),
        sa.ForeignKeyConstraint(["chat_id"], ["chats.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["sender_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_messages")),
        sa.UniqueConstraint(
            "sender_id", "client_message_id", name=op.f("uq_message_sender_client_id")
        ),
    )
    op.create_index(
        op.f("ix_messages_chat_created_id"), "messages", ["chat_id", "created_at", "id"]
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_messages_chat_created_id"), table_name="messages")
    op.drop_table("messages")
