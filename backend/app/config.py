"""Application settings, environment-aware.

Distinguishes local vs production explicitly via `ENVIRONMENT` rather
than inferring it from which vars happen to be set: any code that needs
to behave differently between "running on my machine" and "the real
deployment" reads `settings.environment`, not the presence/absence of a
particular env var. See CLAUDE.md's Environment section and this
module's use in app/db.py (SSL) and app/main.py (docs endpoints).

.env file location is NOT assumed to be `backend/.env` -- real secrets
live in a separate directory outside the repo. Set CELLAR_DOOR_ENV_FILE
to point at it; defaults to backend/.env for the common case of a
local, non-secret dev override file. A missing env_file is not an
error (pydantic-settings' default behavior) -- production reads real
environment variables, not a file.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["local", "production"]

_DEFAULT_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=os.environ.get("CELLAR_DOOR_ENV_FILE", str(_DEFAULT_ENV_FILE)),
        extra="ignore",
    )

    environment: Environment = "local"

    # Two distinct connection strings against the same Supabase Postgres
    # instance -- Supabase's session pooler (port 5432) for Alembic
    # (migrations want a stable, non-multiplexed session), and the
    # transaction pooler (port 6543) for app/db.py's asyncpg pool (short-
    # lived transactional queries, the pattern the transaction pooler is
    # built for). Both default to the standard local-Postgres string
    # (matches .env.example) rather than being required -- importing
    # app.main (or anything that touches Settings) must not hard-fail
    # just because no .env exists yet, e.g. in CI, which sets neither.
    database_url_runtime: str = "postgresql://postgres:postgres@localhost:5432/cellar_door"
    database_url_migrations: str = "postgresql://postgres:postgres@localhost:5432/cellar_door"

    anthropic_api_key: str | None = None

    # Supabase project config, used by app/storage.py (SupabaseStorageClient)
    # and app/auth.py (JWKS verification). Defaulted (not required) for
    # the same reason database_url_* is -- app startup / dependency
    # construction must not hard-fail before real values are set.
    supabase_url: str = "https://REPLACE_WITH_SUPABASE_PROJECT.supabase.co"
    # "Secret key" -- Supabase's current name for the backend-only key
    # that bypasses RLS (formerly "service_role key"; the underlying
    # capability is the same). Never expose this to a client.
    supabase_secret_key: str = "REPLACE_WITH_SUPABASE_SECRET_KEY"
    supabase_jwks_url: str = (
        "https://REPLACE_WITH_SUPABASE_PROJECT.supabase.co/auth/v1/.well-known/jwks.json"
    )


@lru_cache
def get_settings() -> Settings:
    """Process-wide cached Settings instance.

    Cached because Settings() re-reads the env file and environment on
    every construction -- fine for a one-off script, wasteful called on
    every request. Code that needs *different* database_url_* values
    than the real environment's (tests, against a testcontainers
    instance) should not go through this function -- see app/db.py,
    which takes database_url as an explicit parameter instead.
    """
    return Settings()
