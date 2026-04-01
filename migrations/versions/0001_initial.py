"""initial schema: api_keys, links, rollups, processed_events

Revision ID: 0001
Revises:
Create Date: 2026-06-12
"""
import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "api_keys",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("key_hash", sa.Text(), nullable=False, unique=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("rate_capacity", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("refill_per_s", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_api_keys_key_hash", "api_keys", ["key_hash"])

    op.create_table(
        "links",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("short_code", sa.String(12), nullable=False, unique=True),
        sa.Column("long_url", sa.Text(), nullable=False),
        sa.Column("api_key_id", sa.BigInteger(), sa.ForeignKey("api_keys.id"), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("long_url ~* '^https?://'", name="ck_links_scheme"),
    )
    op.create_index("ix_links_api_key_created", "links", ["api_key_id", "created_at"])

    for table in ("click_rollups_hourly", "click_rollups_daily"):
        op.create_table(
            table,
            sa.Column("link_id", sa.BigInteger(), sa.ForeignKey("links.id"), primary_key=True),
            sa.Column("bucket_start", sa.DateTime(timezone=True), primary_key=True),
            sa.Column("clicks", sa.BigInteger(), nullable=False, server_default="0"),
        )

    op.create_table(
        "processed_events",
        sa.Column("event_id", sa.Text(), primary_key=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_processed_events_processed_at", "processed_events", ["processed_at"])


def downgrade() -> None:
    for table in ("processed_events", "click_rollups_daily", "click_rollups_hourly", "links", "api_keys"):
        op.drop_table(table)
