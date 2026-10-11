"""Add replies, mentions, attachments and chat preferences support.

Revision ID: 20261011_0005
Revises: 20261011_0004
Create Date: 2026-10-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261011_0005"
down_revision: str | None = "20261011_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("messages") as batch_op:
        batch_op.add_column(sa.Column("reply_to_message_id", sa.Uuid(as_uuid=True), nullable=True))
        batch_op.create_foreign_key(
            op.f("fk_messages_reply_to_message_id_messages"),
            "messages",
            ["reply_to_message_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index(op.f("ix_messages_reply_to_message_id"), ["reply_to_message_id"])
    op.create_table(
        "message_mentions",
        sa.Column("message_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("message_id", "user_id", name=op.f("pk_message_mentions")),
    )
    op.create_table(
        "message_attachments",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("chat_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("uploaded_by", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("message_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=255), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("storage_name", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["chat_id"], ["chats.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["uploaded_by"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_message_attachments")),
        sa.UniqueConstraint("storage_name", name=op.f("uq_message_attachments_storage_name")),
    )
    op.create_index(
        op.f("ix_message_attachments_message_id"), "message_attachments", ["message_id"]
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_message_attachments_message_id"), table_name="message_attachments")
    op.drop_table("message_attachments")
    op.drop_table("message_mentions")
    with op.batch_alter_table("messages") as batch_op:
        batch_op.drop_index(op.f("ix_messages_reply_to_message_id"))
        batch_op.drop_constraint(
            op.f("fk_messages_reply_to_message_id_messages"), type_="foreignkey"
        )
        batch_op.drop_column("reply_to_message_id")
