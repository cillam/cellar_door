"""Shared pytest fixtures/helpers for backend tests.

`make_mock_provider` is the test double referenced by
`.claude/add-graph-node.md`'s node-test template. Node tests monkeypatch
`app.providers.registry.provider_for` to return one, then assert both
the node's parsed output and the prompt/schema it was called with --
per CLAUDE.md's testing conventions ("Node tests mock the ModelProvider
and assert it was called with the right prompt and schema").
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from app.providers.base import ModelProvider

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
