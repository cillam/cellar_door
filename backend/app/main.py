"""FastAPI entrypoint.

This file's job: boot the app, behave differently in production where
that's security-relevant (docs endpoints), register routers, wire the
DB pool and the compiled LangGraph pipeline into the app lifespan, and
expose a health endpoint for deploy checks (Railway) and CI.

TestClient(app) without a `with` block skips lifespan entirely -- used
throughout tests/test_routes.py for the routes that don't need a live
pool. The item-CRUD routes (POST/GET /items, step 4e) don't override
get_db_pool via app.dependency_overrides, despite that being the
pattern used for get_storage_client/get_current_user_id: a pool built
by a separate pytest-asyncio fixture lives in a different event loop
than the one TestClient's request handling runs in, and asyncpg
connections aren't safe to share across loops. Instead those tests
point DATABASE_URL_RUNTIME/DATABASE_URL_MIGRATIONS at a testcontainers
instance and enter `with TestClient(app) as client:`, so this real
lifespan creates the pool inside TestClient's own loop -- see
tests/test_routes.py's `db_client` fixture.

The from-photo/resume routes (step 5b) are different: get_compiled_graph
*is* overridden via app.dependency_overrides for every test in
tests/test_routes.py (its autouse `graph_override` fixture), because
InMemorySaver is pure in-process state with no cross-event-loop hazard
the way an asyncpg pool or AsyncPostgresSaver's psycopg connection has
-- there's no reason to pay for a real Postgres-backed graph in tests
that don't need one. Compare app/graph/pipeline.py's docstring, which
covers this from the pipeline side.

create_pool and compiled_graph_with_postgres are each exercised
directly elsewhere (tests/test_db.py; the graph, via InMemorySaver, in
tests/test_graph.py), so this file's lifespan is just gluing
already-tested pieces together.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import Environment, get_settings
from app.db import create_pool
from app.graph.pipeline import compiled_graph_with_postgres
from app.routers import items


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    app.state.db_pool = await create_pool(
        settings.database_url_runtime, environment=settings.environment
    )
    try:
        # database_url_migrations (session pooler), not database_url_runtime
        # (transaction pooler) -- see compiled_graph_with_postgres's
        # docstring for why.
        async with compiled_graph_with_postgres(settings.database_url_migrations) as graph:
            app.state.compiled_graph = graph
            yield
    finally:
        await app.state.db_pool.close()


def docs_urls(environment: Environment) -> tuple[str | None, str | None, str | None]:
    """(docs_url, redoc_url, openapi_url) for FastAPI(), by environment.

    A named function rather than inline conditionals so it's testable
    directly (tests/test_routes.py) without reloading app.main under a
    monkeypatched environment. Docs endpoints expose the full
    route/schema surface -- off in production, on everywhere else
    (local dev, CI, tests).
    """
    if environment == "production":
        return None, None, None
    return "/docs", "/redoc", "/openapi.json"


_docs_url, _redoc_url, _openapi_url = docs_urls(get_settings().environment)

app = FastAPI(
    title="Cellar Door API",
    lifespan=lifespan,
    docs_url=_docs_url,
    redoc_url=_redoc_url,
    openapi_url=_openapi_url,
)
app.include_router(items.router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
