"""ModelProvider — the interface every model-calling graph node goes through.

Nodes never import `anthropic` or `langchain_anthropic` directly (see
CLAUDE.md). A provider instance is bound to one graph node — and therefore
one model tier — at construction time, resolved via
`app.providers.registry.provider_for`. `ClaudeProvider` is the only
implementation in the MVP; the interface stays provider-agnostic so the
per-node swaps backlogged in EXPERIMENTS.md (Gemini, local models, a
dedicated OCR model) are a new class + a registry entry, not a node
rewrite.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class ModelProvider(ABC):
    """Provider-agnostic interface for a single graph node's model calls.

    Implementations set `node_name` and `model` in `__init__` so usage
    events (see `app.providers.events`) can be attributed correctly
    without every call site having to repeat them.
    """

    node_name: str
    model: str

    @abstractmethod
    async def complete_text(self, *, prompt: str) -> str:
        """Free-form text-in, text-out completion. No image, no schema."""
        raise NotImplementedError

    @abstractmethod
    async def complete_vision(self, *, prompt: str, image: bytes) -> str:
        """Free-form text-out completion grounded in an image."""
        raise NotImplementedError

    @abstractmethod
    async def complete_structured(
        self, *, prompt: str, schema: type[T], image: bytes | None = None
    ) -> T:
        """Structured-output completion, optionally grounded in an image.

        `schema` is a Pydantic model class; the return value is an
        instance of it. This is what most graph nodes use — see
        `.claude/add-graph-node.md`.
        """
        raise NotImplementedError
