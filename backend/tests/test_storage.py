"""Contract tests for StorageClient, mirroring test_providers.py's
approach for ModelProvider: prove the interface contract via a mock
double, verify a real construction path exists, without hitting the
real Supabase Storage API (no credentials until step 5).
"""

from __future__ import annotations

import httpx
import pytest

from app.storage import StorageClient, SupabaseStorageClient
from tests.conftest import make_mock_storage_client


def _client_with_mock_transport(handler: httpx.MockTransport) -> SupabaseStorageClient:
    """A SupabaseStorageClient whose HTTP calls hit a fake transport
    instead of the network -- lets us test the real URL-building/
    response-handling logic without real Supabase credentials.
    Swaps the private `_client` post-construction, same pattern
    test_providers.py uses for ClaudeProvider's `_client`.
    """
    client = SupabaseStorageClient(
        base_url="https://placeholder.supabase.co",
        service_role_key="placeholder-key",
    )
    client._client = httpx.AsyncClient(
        base_url="https://placeholder.supabase.co",
        headers={"Authorization": "Bearer placeholder-key"},
        transport=handler,
    )
    return client


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


async def test_supabase_storage_client_signed_url_joins_base_url_correctly() -> None:
    # Regression test for PR #17's review: base_url has no trailing
    # slash (as constructed here and as SUPABASE_URL will likely be
    # set), so naive string concatenation produced a malformed URL
    # (missing "/" before "storage"). base_url.join() must handle this
    # regardless of trailing-slash state.
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"signedURL": "/object/sign/bucket/photos/u1/a.jpg?token=abc"}
        )

    client = _client_with_mock_transport(httpx.MockTransport(handler))

    url = await client.signed_url("photos/u1/a.jpg")

    assert url == (
        "https://placeholder.supabase.co/storage/v1/object/sign/bucket/photos/u1/a.jpg?token=abc"
    )


async def test_supabase_storage_client_download_translates_404_to_file_not_found() -> None:
    # Regression test for PR #17's review: MockStorageClient raises
    # FileNotFoundError for a missing object; SupabaseStorageClient must
    # satisfy the same contract on a real 404, not leak httpx's
    # HTTPStatusError, or route code tested against the mock would miss
    # the real case.
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "not found"})

    client = _client_with_mock_transport(httpx.MockTransport(handler))

    with pytest.raises(FileNotFoundError):
        await client.download("photos/u1/missing.jpg")
