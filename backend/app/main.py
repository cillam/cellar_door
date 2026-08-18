"""FastAPI entrypoint.

This file's job: boot the app, behave differently in production where
that's security-relevant (docs endpoints), register routers, wire the
DB pool into the app lifespan, and expose a health endpoint for deploy
checks (Railway) and CI.

The lifespan-created pool is only exercised by the real app (uvicorn);
tests never trigger it -- TestClient(app) without a `with` block skips
lifespan entirely (used throughout tests/test_routes.py for the
routes that don't need a live pool), and the routes that do
(POST/GET /items, step 4e) get their pool via
`app.dependency_overrides[get_db_pool]` in tests instead, pointed at a
testcontainers instance. create_pool itself is exercised directly by
tests/test_db.py, so this file's lifespan is just gluing two
already-tested pieces together.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import Environment, get_settings
from app.db import create_pool
from app.routers import items


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    app.state.db_pool = await create_pool(settings.database_url, environment=settings.environment)
    try:
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
