"""StorageClient -- the interface for Supabase Storage interactions.

Mirrors app/providers/base.py's ModelProvider pattern: an interface now,
plus a real implementation (SupabaseStorageClient) written now with
placeholder config -- same shape as ClaudeProvider's placeholder model
IDs from step 2, filled in with real values once step 5's Supabase
credentials exist. Routes never talk to Supabase Storage directly, and
never import httpx for this -- they go through StorageClient.

Unlike ModelProvider there's no EXPERIMENTS.md backlog of swaps for
this (Supabase Storage is locked in CLAUDE.md's tech stack); the
interface exists so routes and tests depend on a small contract instead
of the Supabase HTTP API shape directly.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import httpx

# Placeholder bucket name. Real Supabase project config (SUPABASE_URL,
# SUPABASE_SERVICE_ROLE_KEY, bucket name) arrives in step 5 -- same
# spirit as claude.py's _MODEL_IDS placeholders from step 2.
_PHOTOS_BUCKET = "REPLACE_WITH_SUPABASE_BUCKET_NAME"


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

    Not exercised for real until step 5's credentials exist -- endpoint
    shapes here match Supabase's documented Storage API as of this
    writing; worth a quick sanity check against current docs once real
    credentials land, the same way claude.py's placeholder model IDs
    need confirming in step 6.
    """

    def __init__(
        self,
        *,
        base_url: str,
        service_role_key: str,
        bucket: str = _PHOTOS_BUCKET,
    ) -> None:
        self._bucket = bucket
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers={"Authorization": f"Bearer {service_role_key}"},
        )

    async def download(self, path: str) -> bytes:
        response = await self._client.get(f"/storage/v1/object/{self._bucket}/{path}")
        if response.status_code == 404:
            raise FileNotFoundError(path)
        response.raise_for_status()
        return response.content

    async def delete(self, path: str) -> None:
        # httpx's .delete() shortcut doesn't accept a body; Supabase's
        # bulk-delete endpoint needs one (a list of paths), so use
        # .request() directly instead.
        response = await self._client.request(
            "DELETE",
            f"/storage/v1/object/{self._bucket}",
            json={"prefixes": [path]},
        )
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
