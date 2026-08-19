"""StorageClient -- the interface for Supabase Storage interactions.

Mirrors app/providers/base.py's ModelProvider pattern: an interface now,
plus a real implementation (SupabaseStorageClient). Routes never talk
to Supabase Storage directly, and never import httpx for this -- they
go through StorageClient.

Unlike ModelProvider there's no EXPERIMENTS.md backlog of swaps for
this (Supabase Storage is locked in CLAUDE.md's tech stack); the
interface exists so routes and tests depend on a small contract instead
of the Supabase HTTP API shape directly.

Endpoint shapes below (`/storage/v1/object/...`) were last verified
against Supabase's docs in step 4b's PR review, not re-confirmed here
(step 5) -- a docs re-check was attempted but the tool was unavailable
mid-session. The real round-trip test against the live 'photos' bucket
is the actual verification that they still hold.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from functools import lru_cache

import httpx

from app.config import get_settings

# Real bucket name (created in the Supabase dashboard, step 5), private.
_PHOTOS_BUCKET = "photos"


class StorageClient(ABC):
    """Interface for the one storage backend this app uses."""

    @abstractmethod
    async def download(self, path: str) -> bytes:
        """Fetch a stored object's bytes -- e.g. a photo for the graph
        pipeline (POST /items/from-photo loads the image this way).

        Raises `FileNotFoundError` if `path` doesn't exist -- both
        implementations (MockStorageClient in tests/conftest.py,
        SupabaseStorageClient below) must satisfy this so route code
        written and tested against the mock (`except FileNotFoundError`)
        also handles the real thing.
        """
        raise NotImplementedError

    @abstractmethod
    async def delete(self, path: str) -> None:
        """Delete a stored object -- e.g. an item's photo on
        DELETE /items/{id}.
        """
        raise NotImplementedError

    @abstractmethod
    async def signed_url(self, path: str, *, expires_in_seconds: int = 3600) -> str:
        """A temporary signed URL for reading an object.

        BaseItem.photo_url (app/models/items.py) is a storage *path*,
        not a usable URL -- its docstring says "Signed URLs are
        generated on read." Routes call this when serializing an item
        for a response (GET /items, GET /items/{id}, the `complete` SSE
        event).
        """
        raise NotImplementedError


class SupabaseStorageClient(StorageClient):
    """Real implementation, over the Supabase Storage HTTP API via
    httpx (CLAUDE.md: "No requests, use httpx").
    """

    def __init__(
        self,
        *,
        base_url: str,
        secret_key: str,
        bucket: str = _PHOTOS_BUCKET,
    ) -> None:
        self._bucket = bucket
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers={"Authorization": f"Bearer {secret_key}"},
        )

    async def download(self, path: str) -> bytes:
        response = await self._client.get(f"/storage/v1/object/{self._bucket}/{path}")
        if response.status_code == 404:
            raise FileNotFoundError(path)
        response.raise_for_status()
        return response.content

    async def delete(self, path: str) -> None:
        # Single-object delete (DELETE /object/{bucket}/{path}, no body)
        # rather than the bulk-delete endpoint (DELETE /object/{bucket},
        # body {"prefixes": [...]}) this used before step 5 -- both are
        # real, valid endpoints (confirmed against Supabase's storage
        # API reference), but the single-object form needs no body and
        # matches download()'s path shape.
        response = await self._client.delete(f"/storage/v1/object/{self._bucket}/{path}")
        response.raise_for_status()

    async def signed_url(self, path: str, *, expires_in_seconds: int = 3600) -> str:
        response = await self._client.post(
            f"/storage/v1/object/sign/{self._bucket}/{path}",
            json={"expiresIn": expires_in_seconds},
        )
        response.raise_for_status()
        signed_path = response.json()["signedURL"]
        # base_url.join() resolves an absolute-path reference correctly
        # regardless of whether base_url itself has a trailing slash --
        # unlike raw string concatenation (see PR #17 review).
        return str(self._client.base_url.join(f"/storage/v1{signed_path}"))


@lru_cache
def get_storage_client() -> StorageClient:
    """FastAPI dependency -- the process-wide StorageClient.

    Routes depend on this (`Depends(get_storage_client)`), never on
    SupabaseStorageClient directly. Tests override it via FastAPI's
    `app.dependency_overrides[get_storage_client] = ...` to inject a
    MockStorageClient instead -- see tests/conftest.py.
    """
    settings = get_settings()
    return SupabaseStorageClient(
        base_url=settings.supabase_url,
        secret_key=settings.supabase_secret_key,
    )
