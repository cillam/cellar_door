"""FastAPI entrypoint.

This file's job: boot the app, behave differently in production where
that's security-relevant (docs endpoints), register routers, and expose
a health endpoint for deploy checks (Railway) and CI. The DB pool isn't
wired into the app lifespan yet -- app/db.py and the items-table
migration exist and are tested (tests/test_db.py, testcontainers), but
nothing routes to them until step 4e (POST/GET /items). Wiring it here
before that would make `uvicorn app.main:app` require a running
Postgres just to serve /health, which it doesn't need today.
"""

from fastapi import FastAPI

from app.config import Environment, get_settings
from app.routers import items


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
    docs_url=_docs_url,
    redoc_url=_redoc_url,
    openapi_url=_openapi_url,
)
app.include_router(items.router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
