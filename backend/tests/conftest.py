"""Shared pytest fixtures/helpers for backend tests.

`make_mock_provider` is the test double referenced by
`.claude/add-graph-node.md`'s node-test template. Node tests monkeypatch
`app.providers.registry.provider_for` to return one, then assert both
the node's parsed output and the prompt/schema it was called with --
per CLAUDE.md's testing conventions ("Node tests mock the ModelProvider
and assert it was called with the right prompt and schema").

`MockStorageClient` is the equivalent test double for app.storage --
route tests (e.g. DELETE /items/{id} deleting the photo) inject one
instead of a real SupabaseStorageClient.

`provider_resolver_for` and `bearer_header` are shared by
tests/test_graph.py (the graph-level end-to-end tests) and
tests/test_routes.py (route tests that run the real graph through the
API layer) -- one node-name-keyed provider mock and one JWT-header
builder, rather than each test file growing its own copy.

`postgres_url`/`db_pool` are the testcontainers-backed Postgres fixtures
shared by tests/test_db.py and tests/test_routes.py -- one real,
migrated container per test session (Docker required) rather than each
file spinning up its own. `database_urls_pointed_at` is the env-var
dance both that fixture and tests/test_routes.py's `db_client` fixture
need (point Settings' DATABASE_URL_RUNTIME/DATABASE_URL_MIGRATIONS at a
testcontainers instance, then restore), factored out to one place.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

import asyncpg
import jwt
import pytest
from alembic.config import Config
from testcontainers.community.postgres import PostgresContainer

from alembic import command
from app.config import get_settings
from app.db import create_pool
from app.providers.base import ModelProvider
from app.storage import StorageClient

FIXTURES_DIR = Path(__file__).parent / "fixtures"
_BACKEND_DIR = Path(__file__).resolve().parent.parent

_DATABASE_URL_ENV_VARS = ("DATABASE_URL_RUNTIME", "DATABASE_URL_MIGRATIONS")


@contextmanager
def database_urls_pointed_at(url: str) -> Iterator[None]:
    """Temporarily point both DATABASE_URL_RUNTIME and
    DATABASE_URL_MIGRATIONS at `url` (a testcontainers instance),
    clearing Settings' cache around the change so get_settings() picks
    it up, then restore whatever was there before (nothing, in CI/local
    dev). Real deployments never hit this -- these two vars are
    genuinely different poolers against real Supabase (see
    app/config.py); tests just need one Postgres to serve both roles.
    """
    originals = {key: os.environ.get(key) for key in _DATABASE_URL_ENV_VARS}
    for key in _DATABASE_URL_ENV_VARS:
        os.environ[key] = url
    get_settings.cache_clear()
    try:
        yield
    finally:
        for key, original in originals.items():
            if original is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = original
        get_settings.cache_clear()


def load_fixture(name: str) -> bytes:
    """Read a fixture file's bytes by name, e.g. load_fixture('placeholder.png')."""
    return (FIXTURES_DIR / name).read_bytes()


@dataclass
class RecordedCall:
    method: Literal["complete_text", "complete_vision", "complete_structured"]
    prompt: str
    schema: type[Any] | None
    image: bytes | None


@dataclass
class MockProvider(ModelProvider):
    """Test double that returns a canned value and records every call."""

    node_name: str = "test_node"
    model: str = "mock-model"
    returns: Any = None
    calls: list[RecordedCall] = field(default_factory=list)

    async def complete_text(self, *, prompt: str) -> str:
        self.calls.append(RecordedCall("complete_text", prompt, None, None))
        return str(self.returns)

    async def complete_vision(self, *, prompt: str, image: bytes) -> str:
        self.calls.append(RecordedCall("complete_vision", prompt, None, image))
        return str(self.returns)

    async def complete_structured(
        self, *, prompt: str, schema: type[Any], image: bytes | None = None
    ) -> Any:
        self.calls.append(RecordedCall("complete_structured", prompt, schema, image))
        return self.returns

    def called_with_prompt_containing(self, substring: str) -> bool:
        return any(substring in call.prompt for call in self.calls)


def make_mock_provider(*, node_name: str = "test_node", returns: Any) -> MockProvider:
    """Build a MockProvider preloaded to return `returns` from any method."""
    return MockProvider(node_name=node_name, returns=returns)


def provider_resolver_for(returns_by_node: dict[str, Any]) -> Callable[[str], MockProvider]:
    """Build a registry.provider_for replacement keyed by node name.

    A single monkeypatch target that dispatches to a different canned
    response per node -- the graph calls provider_for once per
    model-calling node it visits, so one resolver covers a whole run.
    """

    def _resolve(node_name: str) -> MockProvider:
        return make_mock_provider(node_name=node_name, returns=returns_by_node[node_name])

    return _resolve


@dataclass
class MockStorageClient(StorageClient):
    """Test double recording calls, for route tests exercising storage
    interactions without a real Supabase Storage backend.

    `downloads` preloads what `download()` returns per path (raises
    FileNotFoundError for an unseeded path, matching a real 404).
    `deleted_paths` and `signed_url_calls` record what was called.
    """

    downloads: dict[str, bytes] = field(default_factory=dict)
    deleted_paths: list[str] = field(default_factory=list)
    signed_url_calls: list[str] = field(default_factory=list)

    async def download(self, path: str) -> bytes:
        if path not in self.downloads:
            raise FileNotFoundError(path)
        return self.downloads[path]

    async def delete(self, path: str) -> None:
        self.deleted_paths.append(path)

    async def signed_url(self, path: str, *, expires_in_seconds: int = 3600) -> str:
        self.signed_url_calls.append(path)
        return f"https://mock-storage.test/{path}?signed=true&expires_in={expires_in_seconds}"


def make_mock_storage_client(*, downloads: dict[str, bytes] | None = None) -> MockStorageClient:
    """Build a MockStorageClient, optionally preloaded with download() results."""
    return MockStorageClient(downloads=downloads or {})


def bearer_header(user_id: UUID) -> dict[str, str]:
    """An Authorization header carrying an unverified JWT for user_id.

    app.auth.get_current_user_id's stub doesn't check the signature
    (see its module docstring), so any secret works -- the length just
    needs to clear pyjwt's minimum-key-length warning threshold.
    """
    token = jwt.encode(
        {"sub": str(user_id)},
        "test-secret-that-is-long-enough-to-not-warn",
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    """A running Postgres container's plain (asyncpg-style) DSN,
    migrated to head. Session-scoped -- one container, one migration
    run, shared by every test in the session that needs real
    persistence (tests/test_db.py, tests/test_routes.py). Requires
    Docker running locally.
    """
    with PostgresContainer("postgres:16-alpine") as pg:
        url = pg.get_connection_url(driver=None)

        with database_urls_pointed_at(url):
            alembic_cfg = Config(str(_BACKEND_DIR / "alembic.ini"))
            command.upgrade(alembic_cfg, "head")

        yield url


@pytest.fixture
async def db_pool(postgres_url: str) -> AsyncIterator[asyncpg.Pool]:
    """A fresh asyncpg pool per test, against the session-shared
    container above. No truncation between tests -- every test uses a
    fresh random user_id/item id (uuid4()), so rows from different
    tests never collide or become visible to each other's queries.
    """
    pool = await create_pool(postgres_url, environment="local")
    try:
        yield pool
    finally:
        await pool.close()
