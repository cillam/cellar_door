"""Integration test for app/db.py + the items-table migration, run
against a real (ephemeral) Postgres via testcontainers. Requires Docker
running locally.

Distinct from the node/route unit tests elsewhere -- this is the one
place the actual schema and the asyncpg pool get exercised together, so
a broken migration or a pool misconfiguration fails here, not silently
downstream in a router that assumes a column exists.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from uuid import uuid4

import asyncpg
import pytest
from alembic.config import Config
from testcontainers.community.postgres import PostgresContainer

from alembic import command
from app.config import get_settings
from app.db import create_pool

_BACKEND_DIR = Path(__file__).resolve().parent.parent

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


@pytest.fixture(scope="module")
def postgres_url() -> Iterator[str]:
    """A running Postgres container's plain (asyncpg-style) DSN,
    migrated to head. Module-scoped -- one container for this file.
    """
    with PostgresContainer("postgres:16-alpine") as pg:
        url = pg.get_connection_url(driver=None)

        # alembic/env.py reads DATABASE_URL via get_settings(); point it
        # at the container for the duration of the migration, then
        # restore whatever was there (nothing, in CI/local dev).
        original = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = url
        get_settings.cache_clear()
        try:
            alembic_cfg = Config(str(_BACKEND_DIR / "alembic.ini"))
            command.upgrade(alembic_cfg, "head")
        finally:
            if original is None:
                os.environ.pop("DATABASE_URL", None)
            else:
                os.environ["DATABASE_URL"] = original
            get_settings.cache_clear()

        yield url


@pytest.fixture
async def pool(postgres_url: str) -> AsyncIterator[asyncpg.Pool]:
    created_pool = await create_pool(postgres_url, environment="local")
    try:
        yield created_pool
    finally:
        await created_pool.close()


async def test_migration_creates_items_table_with_expected_columns(
    pool: asyncpg.Pool,
) -> None:
    rows = await pool.fetch(
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'items'"
    )
    assert {row["column_name"] for row in rows} == _EXPECTED_COLUMNS


async def test_insert_and_select_item_roundtrip(pool: asyncpg.Pool) -> None:
    item_id = uuid4()
    user_id = uuid4()

    await pool.execute(
        """
        INSERT INTO items (id, user_id, category, photo_url, title, description)
        VALUES ($1, $2, 'wine', 'photos/x/y.jpg', 'A Wine', 'A description')
        """,
        item_id,
        user_id,
    )

    row = await pool.fetchrow("SELECT * FROM items WHERE id = $1", item_id)

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
    pool: asyncpg.Pool,
) -> None:
    with pytest.raises(asyncpg.CheckViolationError):
        await pool.execute(
            """
            INSERT INTO items (id, user_id, category, photo_url, title, description)
            VALUES ($1, $2, 'not-a-real-category', 'photos/x/y.jpg', 'X', 'Y')
            """,
            uuid4(),
            uuid4(),
        )


async def test_confidence_scores_roundtrip_as_dict(pool: asyncpg.Pool) -> None:
    item_id = uuid4()
    await pool.execute(
        """
        INSERT INTO items (id, user_id, category, photo_url, title, description, confidence_scores)
        VALUES ($1, $2, 'wine', 'photos/x/y.jpg', 'A Wine', 'A description', $3)
        """,
        item_id,
        uuid4(),
        {"producer": 0.9, "vintage": 0.5},
    )

    row = await pool.fetchrow("SELECT confidence_scores FROM items WHERE id = $1", item_id)

    assert row is not None
    assert row["confidence_scores"] == {"producer": 0.9, "vintage": 0.5}
