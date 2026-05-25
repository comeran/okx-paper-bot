"""Initial SQLAlchemy schema.

Revision ID: 0001_init
Revises:
Create Date: 2026-05-20
"""
from __future__ import annotations

from alembic import op

from okx_paper_bot.persistence.models import Base

revision = "0001_init"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(op.get_bind())
