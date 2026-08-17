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
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from app.providers.base import ModelProvider
from app.storage import StorageClient

FIXTURES_DIR = Path(__file__).parent / "fixtures"


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
