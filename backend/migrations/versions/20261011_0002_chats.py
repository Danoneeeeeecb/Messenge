"""Create chats and membership tables.

Revision ID: 20261011_0002
Revises: 20261011_0001
Create Date: 2026-10-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261011_0002"
down_revision: str | None = "20261011_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "chats",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("type", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=True),
        sa.Column("created_by", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("direct_user_low_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("direct_user_high_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(type = 'direct' AND title IS NULL AND direct_user_low_id IS NOT NULL "
            "AND direct_user_high_id IS NOT NULL AND direct_user_low_id < direct_user_high_id) "
            "OR (type = 'group' AND title IS NOT NULL AND direct_user_low_id IS NULL "
            "AND direct_user_high_id IS NULL)",
            name=op.f("ck_chats_chat_type_fields"),
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["direct_user_high_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["direct_user_low_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chats")),
        sa.UniqueConstraint(
            "direct_user_low_id", "direct_user_high_id", name=op.f("uq_direct_chat_pair")
        ),
    )
    op.create_index(op.f("ix_chats_last_message_at"), "chats", ["last_message_at"])

    op.create_table(
        "chat_members",
        sa.Column("chat_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column(
            "joined_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("muted", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("last_read_message_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.CheckConstraint(
            "role IN ('admin', 'member')", name=op.f("ck_chat_members_chat_member_role")
        ),
        sa.ForeignKeyConstraint(["chat_id"], ["chats.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("chat_id", "user_id", name=op.f("pk_chat_members")),
    )
    op.create_index(op.f("ix_chat_members_user_id"), "chat_members", ["user_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_chat_members_user_id"), table_name="chat_members")
    op.drop_table("chat_members")
    op.drop_index(op.f("ix_chats_last_message_at"), table_name="chats")
    op.drop_table("chats")
