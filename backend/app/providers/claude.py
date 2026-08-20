"""ClaudeProvider — the only ModelProvider implementation in the MVP.

Wraps `langchain_anthropic.ChatAnthropic`. Nodes never import this module
directly; they resolve a provider via `app.providers.registry.provider_for`.
See CLAUDE.md's `ModelProvider` conventions.

Real model IDs and pricing (step 6) -- tests never make real Claude
calls (CLAUDE.md: "Claude API calls in CI" are explicitly out of scope;
tests/test_providers.py mocks `_client`'s methods). Real runs happen
node-by-node against fixture images the user provides, one node's
prompt/behavior verified and committed at a time -- see step 6's plan.
"""

from __future__ import annotations

import base64
import time
from typing import Literal, TypeVar, cast

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from pydantic import BaseModel

from app.config import get_settings
from app.providers.base import ModelProvider
from app.providers.events import UsageEvent, emit_usage_event

T = TypeVar("T", bound=BaseModel)

ModelTier = Literal["haiku", "sonnet"]

# Real Anthropic model IDs (step 6) -- see SPEC.md's Model Tiering table
# for the intended tier per node. Centralized here so picking a model is
# a one-line-per-tier change, not a code change. Current as of the
# category_router swap (step 6, node 1 of 5); confirmed against
# platform.claude.com/docs/en/about-claude/pricing at that time.
_MODEL_IDS: dict[ModelTier, str] = {
    "haiku": "claude-haiku-4-5-20251001",
    "sonnet": "claude-sonnet-5",
}

# $/1M-token pricing (input, output), confirmed against
# platform.claude.com/docs/en/about-claude/pricing at the same time as
# the model IDs above -- re-verify both together if either is revisited,
# since a stale price paired with a current model silently mis-estimates
# every eval report's cost column.
_PRICING_PER_MILLION_TOKENS: dict[ModelTier, tuple[float, float]] = {
    "haiku": (1.0, 5.0),
    "sonnet": (2.0, 10.0),
}


class ClaudeProvider(ModelProvider):
    """Anthropic implementation of ModelProvider, bound to one graph node."""

    def __init__(self, *, node_name: str, tier: ModelTier) -> None:
        self.node_name = node_name
        self.tier = tier
        self.model = _MODEL_IDS[tier]
        # Explicit api_key -- without it, ChatAnthropic falls back to the
        # raw ANTHROPIC_API_KEY OS env var, not Settings.anthropic_api_key
        # (loaded from CELLAR_DOOR_ENV_FILE), silently bypassing our
        # env-file-based secret loading until the first real call fails.
        self._client = ChatAnthropic(model=self.model, api_key=get_settings().anthropic_api_key)

    async def complete_text(self, *, prompt: str) -> str:
        start = time.monotonic()
        response = await self._client.ainvoke([HumanMessage(content=prompt)])
        self._emit_usage(start, response)
        return str(response.content)

    async def complete_vision(self, *, prompt: str, image: bytes) -> str:
        start = time.monotonic()
        response = await self._client.ainvoke([self._vision_message(prompt, image)])
        self._emit_usage(start, response)
        return str(response.content)

    async def complete_structured(
        self, *, prompt: str, schema: type[T], image: bytes | None = None
    ) -> T:
        start = time.monotonic()
        message: BaseMessage = (
            self._vision_message(prompt, image)
            if image is not None
            else HumanMessage(content=prompt)
        )
        structured_client = self._client.with_structured_output(schema, include_raw=True)
        raw_response = cast(dict[str, object], await structured_client.ainvoke([message]))
        self._emit_usage(start, cast(BaseMessage, raw_response["raw"]))
        parsed = raw_response.get("parsed")
        if parsed is None:
            raise ValueError(
                f"{self.node_name}: Claude returned output that didn't match {schema.__name__}"
            )
        return cast(T, parsed)

    def _vision_message(self, prompt: str, image: bytes) -> HumanMessage:
        encoded = base64.b64encode(image).decode("ascii")
        return HumanMessage(
            content=[
                {"type": "text", "text": prompt},
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/jpeg",
                        "data": encoded,
                    },
                },
            ]
        )

    def _emit_usage(self, start: float, response: BaseMessage) -> None:
        latency_ms = (time.monotonic() - start) * 1000
        input_tokens = 0
        output_tokens = 0
        if isinstance(response, AIMessage) and response.usage_metadata is not None:
            input_tokens = response.usage_metadata.get("input_tokens", 0)
            output_tokens = response.usage_metadata.get("output_tokens", 0)
        input_price, output_price = _PRICING_PER_MILLION_TOKENS[self.tier]
        estimated_cost = (
            input_tokens / 1_000_000 * input_price + output_tokens / 1_000_000 * output_price
        )
        emit_usage_event(
            UsageEvent(
                node_name=self.node_name,
                provider="claude",
                model=self.model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_ms=latency_ms,
                estimated_cost_usd=estimated_cost,
            )
        )
