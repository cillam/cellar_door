"""Database connection pool. Raw asyncpg -- no ORM (CLAUDE.md: "DB calls
via asyncpg"). Migrations are Alembic's job (backend/alembic/), using a
separate sync driver -- this module and Alembic never share a
connection.
"""

from __future__ import annotations

import json

import asyncpg
from fastapi import Request

from app.config import Environment


async def _register_json_codecs(connection: asyncpg.Connection) -> None:
    """Decode jsonb/json columns as Python objects, not raw text.

    asyncpg returns JSON(B) columns as strings by default. confidence_scores
    and details (both jsonb, see the items-table migration) need to
    round-trip as plain dicts for the routers to work with them
    directly, so every pooled connection gets this codec registered.
    """
    for pg_type in ("jsonb", "json"):
        await connection.set_type_codec(
            pg_type,
            encoder=json.dumps,
            decoder=json.loads,
            schema="pg_catalog",
        )


async def create_pool(database_url: str, *, environment: Environment = "local") -> asyncpg.Pool:
    """Create an asyncpg connection pool.

    Takes `database_url` explicitly rather than reading
    app.config.get_settings() itself, so tests can point it at a
    testcontainers instance without fighting a cached Settings
    singleton. The FastAPI app wires the real value from
    get_settings().database_url at startup (see app/main.py).

    SSL is required in production -- Supabase requires it for external
    connections -- and left at asyncpg's default ('prefer': try SSL,
    fall back to plain) locally, where a dev Postgres usually isn't
    configured for it.
    """
    ssl = "require" if environment == "production" else None
    return await asyncpg.create_pool(dsn=database_url, ssl=ssl, init=_register_json_codecs)


async def get_db_pool(request: Request) -> asyncpg.Pool:
    """FastAPI dependency -- the process-wide pool, created once at app
    startup (see app/main.py's lifespan) and stored on app.state.

    Routes depend on this (`Depends(get_db_pool)`) rather than reaching
    for a module-level pool directly, so tests can override it via
    `app.dependency_overrides[get_db_pool] = ...` with a
    testcontainers-backed pool -- same pattern as
    app.storage.get_storage_client.
    """
    return request.app.state.db_pool
