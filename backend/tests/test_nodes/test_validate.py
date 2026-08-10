"""Unit tests for app.graph.nodes.validate -- the non-model Pydantic check."""

from __future__ import annotations

from uuid import uuid4

from app.graph.nodes.validate import validate
from app.graph.state import GraphState
from tests.conftest import load_fixture


async def test_validate_passes_through_valid_fields() -> None:
    state = GraphState(
        image=load_fixture("placeholder.png"),
        user_id=uuid4(),
        confirmed_category="wine",
        structured_fields={
            "producer": "Beringer",
            "varietal": "Cabernet Sauvignon",
            "vintage": 2019,
            "region": None,
            "country": None,
            "bottle_size": None,
        },
        confidence_scores={"producer": 0.9, "vintage": 0.95},
    )
    result = await validate(state)

    assert result.structured_fields == state.structured_fields
    assert result.confidence_scores == state.confidence_scores
    assert result.validation_errors == []


async def test_validate_blanks_invalid_field_and_flags_confidence() -> None:
    state = GraphState(
        image=load_fixture("placeholder.png"),
        user_id=uuid4(),
        confirmed_category="wine",
        structured_fields={
            "producer": "Beringer",
            "varietal": None,
            "vintage": 3000,  # outside WineFields' ge=1800/le=2100 range
            "region": None,
            "country": None,
            "bottle_size": None,
        },
        confidence_scores={"producer": 0.9, "vintage": 0.95},
    )
    result = await validate(state)

    assert result.structured_fields is not None
    assert result.structured_fields["vintage"] is None
    assert result.structured_fields["producer"] == "Beringer"  # untouched
    assert result.confidence_scores["vintage"] == 0.0
    assert result.confidence_scores["producer"] == 0.9  # untouched
    assert len(result.validation_errors) == 1


async def test_validate_skipped_for_other_category() -> None:
    state = GraphState(
        image=load_fixture("placeholder.png"), user_id=uuid4(), confirmed_category="other"
    )
    result = await validate(state)

    assert result.structured_fields is None
    assert result.validation_errors == []


async def test_validate_skipped_when_no_structured_fields() -> None:
    state = GraphState(
        image=load_fixture("placeholder.png"), user_id=uuid4(), confirmed_category="wine"
    )
    result = await validate(state)

    assert result.structured_fields is None
    assert result.validation_errors == []
