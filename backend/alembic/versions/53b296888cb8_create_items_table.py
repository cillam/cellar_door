"""create items table

Revision ID: 53b296888cb8
Revises:
Create Date: 2026-08-14 14:02:39.504300

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "53b296888cb8"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the items table.

    Base BaseItem fields (app/models/items.py) as real columns;
    category-specific fields (WineItem/HalloweenItem's) in a JSONB
    `details` column -- SPEC.md's Schemas section. `gen_random_uuid()`
    is built into Postgres core since v13, no extension needed.
    """
    op.create_table(
        "items",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("photo_url", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("estimated_value", sa.Numeric(), nullable=True),
        sa.Column(
            "confidence_scores",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "details",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "category IN ('wine', 'halloween', 'other')", name="items_category_check"
        ),
    )
    op.create_index("ix_items_user_id", "items", ["user_id"])
    op.create_index(
        "ix_items_user_id_created_at",
        "items",
        ["user_id", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    """Drop the items table."""
    op.drop_index("ix_items_user_id_created_at", table_name="items")
    op.drop_index("ix_items_user_id", table_name="items")
    op.drop_table("items")
