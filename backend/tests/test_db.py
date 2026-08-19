"""Integration test for app/db.py + the items-table migration, run
against a real (ephemeral) Postgres via testcontainers. Requires Docker
running locally. The postgres_url/db_pool fixtures live in conftest.py,
shared with tests/test_routes.py.

Distinct from the node/route unit tests elsewhere -- this is the one
place the actual schema and the asyncpg pool get exercised together, so
a broken migration or a pool misconfiguration fails here, not silently
downstream in a router that assumes a column exists.
"""

from __future__ import annotations

from uuid import uuid4

import asyncpg
import pytest

_EXPECTED_COLUMNS = {
    "id",
    "user_id",
    "category",
    "photo_url",
    "title",
    "description",
    "notes",
    "estimated_value",
    "confidence_scores",
    "details",
    "created_at",
    "updated_at",
}


async def test_migration_creates_items_table_with_expected_columns(
    db_pool: asyncpg.Pool,
) -> None:
    rows = await db_pool.fetch(
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'items'"
    )
    assert {row["column_name"] for row in rows} == _EXPECTED_COLUMNS


async def test_insert_and_select_item_roundtrip(db_pool: asyncpg.Pool) -> None:
    item_id = uuid4()
    user_id = uuid4()

    await db_pool.execute(
        """
        INSERT INTO items (id, user_id, category, photo_url, title, description)
        VALUES ($1, $2, 'wine', 'photos/x/y.jpg', 'A Wine', 'A description')
        """,
        item_id,
        user_id,
    )

    row = await db_pool.fetchrow("SELECT * FROM items WHERE id = $1", item_id)

    assert row is not None
    assert row["user_id"] == user_id
    assert row["category"] == "wine"
    assert row["photo_url"] == "photos/x/y.jpg"
    assert row["notes"] is None
    assert row["estimated_value"] is None
    # jsonb columns decode to real dicts, not raw JSON strings, thanks
    # to create_pool's codec registration.
    assert row["confidence_scores"] == {}
    assert row["details"] == {}
    assert row["created_at"] is not None
    assert row["updated_at"] is not None


async def test_category_check_constraint_rejects_invalid_category(
    db_pool: asyncpg.Pool,
) -> None:
    with pytest.raises(asyncpg.CheckViolationError):
        await db_pool.execute(
            """
            INSERT INTO items (id, user_id, category, photo_url, title, description)
            VALUES ($1, $2, 'not-a-real-category', 'photos/x/y.jpg', 'X', 'Y')
            """,
            uuid4(),
            uuid4(),
        )


async def test_confidence_scores_roundtrip_as_dict(db_pool: asyncpg.Pool) -> None:
    item_id = uuid4()
    await db_pool.execute(
        """
        INSERT INTO items (id, user_id, category, photo_url, title, description, confidence_scores)
        VALUES ($1, $2, 'wine', 'photos/x/y.jpg', 'A Wine', 'A description', $3)
        """,
        item_id,
        uuid4(),
        {"producer": 0.9, "vintage": 0.5},
    )

    row = await db_pool.fetchrow("SELECT confidence_scores FROM items WHERE id = $1", item_id)

    assert row is not None
    assert row["confidence_scores"] == {"producer": 0.9, "vintage": 0.5}
