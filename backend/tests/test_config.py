"""Unit tests for app.config.Settings / get_settings."""

from __future__ import annotations

import pytest

from app.config import Settings, get_settings


def test_settings_defaults_to_local_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    # _env_file=None: don't let a real backend/.env on this machine leak
    # into the test -- this asserts the *default*, not whatever's local.
    settings = Settings(_env_file=None)
    assert settings.environment == "local"


def test_settings_reads_environment_from_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    settings = Settings(_env_file=None)
    assert settings.environment == "production"


def test_settings_database_urls_have_local_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL_RUNTIME", raising=False)
    monkeypatch.delenv("DATABASE_URL_MIGRATIONS", raising=False)
    settings = Settings(_env_file=None)
    assert settings.database_url_runtime.startswith("postgresql://")
    assert settings.database_url_migrations.startswith("postgresql://")


def test_get_settings_is_cached() -> None:
    assert get_settings() is get_settings()
