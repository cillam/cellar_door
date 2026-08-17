"""Contract tests for StorageClient, mirroring test_providers.py's
approach for ModelProvider: prove the interface contract via a mock
double, verify a real construction path exists, without hitting the
real Supabase Storage API (no credentials until step 5).
"""

from __future__ import annotations

import pytest

from app.storage import StorageClient, SupabaseStorageClient
from tests.conftest import make_mock_storage_client


def test_storage_client_is_abstract() -> None:
    # StorageClient declares abstract methods; direct instantiation
    # must fail at runtime, not just in a type checker.
    with pytest.raises(TypeError):
        StorageClient()  # type: ignore[abstract]


async def test_mock_storage_client_download_returns_seeded_bytes() -> None:
    client = make_mock_storage_client(downloads={"photos/u1/a.jpg": b"fake-image-bytes"})
    result = await client.download("photos/u1/a.jpg")
    assert result == b"fake-image-bytes"


async def test_mock_storage_client_download_raises_for_unseeded_path() -> None:
    client = make_mock_storage_client()
    with pytest.raises(FileNotFoundError):
        await client.download("photos/u1/missing.jpg")


async def test_mock_storage_client_delete_records_path() -> None:
    client = make_mock_storage_client()
    await client.delete("photos/u1/a.jpg")
    assert client.deleted_paths == ["photos/u1/a.jpg"]


async def test_mock_storage_client_signed_url_records_call_and_returns_a_url() -> None:
    client = make_mock_storage_client()
    url = await client.signed_url("photos/u1/a.jpg", expires_in_seconds=120)
    assert client.signed_url_calls == ["photos/u1/a.jpg"]
    assert url.startswith("https://")


def test_supabase_storage_client_constructs_without_real_credentials() -> None:
    # Mirrors ClaudeProvider's construction test from test_providers.py --
    # placeholder config is enough to build the client; the real HTTP
    # calls (untested here) only work once step 5's credentials exist.
    client = SupabaseStorageClient(
        base_url="https://placeholder.supabase.co",
        service_role_key="placeholder-key",
    )
    assert isinstance(client, StorageClient)
