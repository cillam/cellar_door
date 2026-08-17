"""Application settings, environment-aware.

Distinguishes local vs production explicitly via `ENVIRONMENT` rather
than inferring it from which vars happen to be set: any code that needs
to behave differently between "running on my machine" and "the real
deployment" reads `settings.environment`, not the presence/absence of a
particular env var. See CLAUDE.md's Environment section and this
module's use in app/db.py (SSL) and app/main.py (docs endpoints).

.env file location is NOT assumed to be `backend/.env` -- real secrets
may live in a separate directory outside the repo. Set ENV_FILE to
point at it; defaults to backend/.env for the common case of a local,
non-secret dev override file. A missing env_file is not an error
(pydantic-settings' default behavior) -- production reads real
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
        env_file=os.environ.get("ENV_FILE", str(_DEFAULT_ENV_FILE)),
        extra="ignore",
    )

    environment: Environment = "local"
    # Defaults to the standard local-Postgres connection string (matches
    # .env.example) rather than being required -- importing app.main (or
    # anything that touches Settings) must not hard-fail just because no
    # .env exists yet, e.g. in CI, which sets no DATABASE_URL at all.
    # Real deployments (Railway, step 7) override this via a real env var.
    database_url: str = "postgresql://postgres:postgres@localhost:5432/cellar_door"
    anthropic_api_key: str | None = None


@lru_cache
def get_settings() -> Settings:
    """Process-wide cached Settings instance.

    Cached because Settings() re-reads the env file and environment on
    every construction -- fine for a one-off script, wasteful called on
    every request. Code that needs a *different* database_url than the
    real environment's (tests, against a testcontainers instance) should
    not go through this function -- see app/db.py, which takes
    database_url as an explicit parameter instead.
    """
    return Settings()
