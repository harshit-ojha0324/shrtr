"""widen links.short_code to 32 chars for longer custom aliases

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-21
"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # widening a varchar is a catalog-only change in PostgreSQL: no table rewrite
    op.alter_column("links", "short_code", type_=sa.String(32), existing_nullable=False)


def downgrade() -> None:
    # fails if any alias is longer than 12 chars, which is the safe outcome
    op.alter_column("links", "short_code", type_=sa.String(12), existing_nullable=False)
