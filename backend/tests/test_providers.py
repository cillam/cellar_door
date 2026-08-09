"""Contract tests for the ModelProvider interface.

These test the *interface contract* (return types match the declared
signatures, every call emits exactly one UsageEvent) -- not model
quality, which is what backend/evals/ is for. ClaudeProvider is tested
here with the underlying langchain client mocked; real Claude calls
never happen in this suite (CLAUDE.md: Claude API calls are explicitly
out of scope for tests, real Claude runs only in evals).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage
from pydantic import BaseModel

from app.providers.base import ModelProvider
from app.providers.claude import ClaudeProvider
from app.providers.events import UsageEvent
from app.providers.registry import NODE_MODEL_CONFIG, provider_for


class _Extraction(BaseModel):
    """Dummy structured-output schema for contract tests."""

    value: str | None = None


class MockProvider(ModelProvider):
    """Minimal ModelProvider test double.

    Node unit tests (step 3+) get their own richer mocks per
    .claude/add-graph-node.md; this one exists to prove the ModelProvider
    contract itself, independent of any real implementation.
    """

    def __init__(self, *, node_name: str = "mock_node", model: str = "mock-model") -> None:
        self.node_name = node_name
        self.model = model

    async def complete_text(self, *, prompt: str) -> str:
        return f"text response to: {prompt}"

    async def complete_vision(self, *, prompt: str, image: bytes) -> str:
        return f"vision response to: {prompt} ({len(image)} bytes)"

    async def complete_structured(
        self, *, prompt: str, schema: type[Any], image: bytes | None = None
    ) -> Any:
        return schema(value=prompt)


def test_model_provider_is_abstract() -> None:
    # ModelProvider declares abstract methods; direct instantiation must
    # fail at runtime, not just in a type checker.
    with pytest.raises(TypeError):
        ModelProvider()  # type: ignore[abstract]


async def test_mock_provider_complete_text_returns_str() -> None:
    provider = MockProvider()
    result = await provider.complete_text(prompt="hello")
    assert isinstance(result, str)


async def test_mock_provider_complete_vision_returns_str() -> None:
    provider = MockProvider()
    result = await provider.complete_vision(prompt="hello", image=b"fake-bytes")
    assert isinstance(result, str)


async def test_mock_provider_complete_structured_returns_schema_instance() -> None:
    provider = MockProvider()
    result = await provider.complete_structured(prompt="hello", schema=_Extraction)
    assert isinstance(result, _Extraction)
    assert result.value == "hello"


# --- registry ----------------------------------------------------------


@pytest.mark.parametrize("node_name", list(NODE_MODEL_CONFIG))
def test_provider_for_resolves_every_configured_node(node_name: str) -> None:
    provider = provider_for(node_name)
    assert isinstance(provider, ClaudeProvider)
    assert provider.node_name == node_name
    assert provider.tier == NODE_MODEL_CONFIG[node_name]


def test_provider_for_matches_spec_model_tiering_table() -> None:
    # SPEC.md's Model Tiering table. `validate` is deliberately absent --
    # it's a pure-Pydantic node with no model call.
    assert NODE_MODEL_CONFIG == {
        "category_router": "haiku",
        "identify": "sonnet",
        "ocr": "sonnet",
        "generate_description_and_title": "haiku",
        "extract_structured": "sonnet",
    }


def test_provider_for_unknown_node_raises() -> None:
    with pytest.raises(ValueError, match="validate"):
        provider_for("validate")


# --- ClaudeProvider usage-event emission --------------------------------


def _make_ai_message(content: str, input_tokens: int, output_tokens: int) -> AIMessage:
    return AIMessage(
        content=content,
        usage_metadata={
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        },
    )


async def test_claude_provider_complete_text_emits_usage_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = ClaudeProvider(node_name="category_router", tier="haiku")
    canned = _make_ai_message("suggested category", input_tokens=100, output_tokens=20)
    # ChatAnthropic is a pydantic model -- it rejects setting non-field
    # attributes on an *instance*. Patch the class instead; plain
    # callables (AsyncMock, lambdas) aren't descriptors, so they aren't
    # auto-bound with `self` when looked up through an instance.
    monkeypatch.setattr(type(provider._client), "ainvoke", AsyncMock(return_value=canned))

    captured: list[UsageEvent] = []
    monkeypatch.setattr(
        "app.providers.claude.emit_usage_event", lambda event: captured.append(event)
    )

    result = await provider.complete_text(prompt="describe this")

    assert result == "suggested category"
    assert len(captured) == 1
    event = captured[0]
    assert event.node_name == "category_router"
    assert event.provider == "claude"
    assert event.model == provider.model
    assert event.input_tokens == 100
    assert event.output_tokens == 20
    assert event.latency_ms >= 0


async def test_claude_provider_complete_structured_returns_parsed_and_emits_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = ClaudeProvider(node_name="extract_structured", tier="sonnet")
    canned_raw = _make_ai_message("raw model output", input_tokens=200, output_tokens=50)
    canned_parsed = _Extraction(value="parsed field")

    class _FakeStructuredClient:
        async def ainvoke(self, _messages: object) -> dict[str, object]:
            return {"raw": canned_raw, "parsed": canned_parsed}

    monkeypatch.setattr(
        type(provider._client),
        "with_structured_output",
        lambda *a, **kw: _FakeStructuredClient(),
    )

    captured: list[UsageEvent] = []
    monkeypatch.setattr(
        "app.providers.claude.emit_usage_event", lambda event: captured.append(event)
    )

    result = await provider.complete_structured(prompt="extract fields", schema=_Extraction)

    assert result is canned_parsed
    assert len(captured) == 1
    assert captured[0].input_tokens == 200
    assert captured[0].output_tokens == 50


async def test_claude_provider_complete_structured_raises_on_unparseable_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = ClaudeProvider(node_name="extract_structured", tier="sonnet")
    canned_raw = _make_ai_message("raw model output", input_tokens=10, output_tokens=5)

    class _FakeStructuredClient:
        async def ainvoke(self, _messages: object) -> dict[str, object]:
            return {"raw": canned_raw, "parsed": None}

    monkeypatch.setattr(
        type(provider._client),
        "with_structured_output",
        lambda *a, **kw: _FakeStructuredClient(),
    )
    monkeypatch.setattr("app.providers.claude.emit_usage_event", lambda _event: None)

    with pytest.raises(ValueError, match="extract_structured"):
        await provider.complete_structured(prompt="extract fields", schema=_Extraction)
