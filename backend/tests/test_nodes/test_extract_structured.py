"""Unit tests for app.graph.nodes.extract_structured."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.graph.nodes.extract_structured import extract_structured
from app.graph.schemas import (
    HalloweenExtractionResult,
    HalloweenFields,
    IdentifyOutput,
    OcrOutput,
    WineExtractionResult,
    WineFields,
)
from app.graph.state import GraphState
from app.providers import registry
from tests.conftest import load_fixture, make_mock_provider


async def test_extract_structured_wine(monkeypatch: pytest.MonkeyPatch) -> None:
    canned = WineExtractionResult(
        fields=WineFields(producer="Beringer", varietal="Cabernet Sauvignon", vintage=2019),
        confidence_scores={"producer": 0.9, "varietal": 0.85, "vintage": 0.95},
    )
    mock = make_mock_provider(node_name="extract_structured", returns=canned)
    monkeypatch.setattr(registry, "provider_for", lambda node_name: mock)

    state = GraphState(
        image=load_fixture("placeholder.png"), user_id=uuid4(), confirmed_category="wine"
    )
    result = await extract_structured(state)

    assert result.structured_fields == {
        "producer": "Beringer",
        "varietal": "Cabernet Sauvignon",
        "vintage": 2019,
        "region": None,
        "country": None,
        "bottle_size": None,
    }
    assert result.confidence_scores["producer"] == 0.9
    call = mock.calls[0]
    assert call.schema is WineExtractionResult
    assert call.image == state.image


async def test_extract_structured_halloween(monkeypatch: pytest.MonkeyPatch) -> None:
    canned = HalloweenExtractionResult(
        fields=HalloweenFields(manufacturer="Funko", character_or_series="Jack Skellington"),
        confidence_scores={"manufacturer": 0.8, "character_or_series": 0.75},
    )
    mock = make_mock_provider(node_name="extract_structured", returns=canned)
    monkeypatch.setattr(registry, "provider_for", lambda node_name: mock)

    state = GraphState(
        image=load_fixture("placeholder.png"), user_id=uuid4(), confirmed_category="halloween"
    )
    result = await extract_structured(state)

    assert result.structured_fields is not None
    assert result.structured_fields["manufacturer"] == "Funko"
    assert result.structured_fields["character_or_series"] == "Jack Skellington"
    call = mock.calls[0]
    assert call.schema is HalloweenExtractionResult
    assert call.image == state.image


async def test_extract_structured_forces_condition_null_even_if_model_populates_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # condition is prompt-discouraged but schema-permitted -- SPEC.md and
    # items.py are explicit it's a user judgment call, never
    # AI-populated. A non-compliant model shouldn't be able to sneak a
    # value -- or a confidence score for that value -- through.
    canned = HalloweenExtractionResult(
        fields=HalloweenFields(manufacturer="Funko", condition="mint"),
        confidence_scores={"manufacturer": 0.8, "condition": 0.7},
    )
    mock = make_mock_provider(node_name="extract_structured", returns=canned)
    monkeypatch.setattr(registry, "provider_for", lambda node_name: mock)

    state = GraphState(
        image=load_fixture("placeholder.png"), user_id=uuid4(), confirmed_category="halloween"
    )
    result = await extract_structured(state)

    assert result.structured_fields is not None
    assert result.structured_fields["condition"] is None
    assert result.structured_fields["manufacturer"] == "Funko"  # untouched
    assert "condition" not in result.confidence_scores
    assert result.confidence_scores["manufacturer"] == 0.8  # untouched


async def test_extract_structured_skipped_for_other(monkeypatch: pytest.MonkeyPatch) -> None:
    mock = make_mock_provider(node_name="extract_structured", returns=None)
    monkeypatch.setattr(registry, "provider_for", lambda node_name: mock)

    state = GraphState(
        image=load_fixture("placeholder.png"), user_id=uuid4(), confirmed_category="other"
    )
    result = await extract_structured(state)

    assert result.structured_fields is None
    assert len(mock.calls) == 0  # never called the provider


async def test_extract_structured_skips_when_category_unconfirmed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Defensive path -- shouldn't happen via the real graph (conditional
    # routing only reaches this node once confirmed_category is set),
    # but confirmed_category is Optional on GraphState.
    mock = make_mock_provider(node_name="extract_structured", returns=None)
    monkeypatch.setattr(registry, "provider_for", lambda node_name: mock)

    state = GraphState(image=load_fixture("placeholder.png"), user_id=uuid4())
    result = await extract_structured(state)

    assert result.structured_fields is None
    assert len(mock.calls) == 0


async def test_extract_structured_includes_identify_and_ocr_context_in_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canned = WineExtractionResult(fields=WineFields(), confidence_scores={})
    mock = make_mock_provider(node_name="extract_structured", returns=canned)
    monkeypatch.setattr(registry, "provider_for", lambda node_name: mock)

    state = GraphState(
        image=load_fixture("placeholder.png"),
        user_id=uuid4(),
        confirmed_category="wine",
        identify_result=IdentifyOutput(best_guess="a Beringer Cabernet", confidence=0.8),
        ocr_result=OcrOutput(state="text_present", text="BERINGER 2019", reason=None),
    )
    await extract_structured(state)

    prompt = mock.calls[0].prompt
    assert "a Beringer Cabernet" in prompt
    assert "BERINGER 2019" in prompt
