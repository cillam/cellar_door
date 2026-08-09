"""Resolves node name -> provider -> model tier.

Model selection per node is configuration, not code (CLAUDE.md). Change a
node's tier by editing NODE_MODEL_CONFIG; no node code changes. Tiers per
SPEC.md's Model Tiering table. `validate` is a pure-Pydantic node with no
model call, so it has no entry here.
"""

from __future__ import annotations

from app.providers.base import ModelProvider
from app.providers.claude import ClaudeProvider, ModelTier

NODE_MODEL_CONFIG: dict[str, ModelTier] = {
    "category_router": "haiku",
    "identify": "sonnet",
    "ocr": "sonnet",
    "generate_description_and_title": "haiku",
    "extract_structured": "sonnet",
}


def provider_for(node_name: str) -> ModelProvider:
    """Resolve the configured ModelProvider for a graph node.

    Raises ValueError if the node has no tier configured -- e.g.
    `validate` (makes no model call) or a typo'd node name.
    """
    try:
        tier = NODE_MODEL_CONFIG[node_name]
    except KeyError as exc:
        raise ValueError(f"No model tier configured for node {node_name!r}") from exc
    return ClaudeProvider(node_name=node_name, tier=tier)
