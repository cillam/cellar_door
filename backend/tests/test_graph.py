"""End-to-end test for the LangGraph pipeline, including the
await_category interrupt and resume, and the extract_structured skip
for "other". Mocked provider throughout -- real Claude runs only in
backend/evals/ (once it exists), per CLAUDE.md.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import uuid4

import pytest
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command

from app.graph.pipeline import compiled_graph
from app.graph.schemas import (
    CategoryRouterOutput,
    DescriptionOutput,
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


def _provider_resolver(
    returns_by_node: dict[str, Any],
) -> Callable[[str], Any]:
    """Build a registry.provider_for replacement keyed by node name.

    A single monkeypatch target that dispatches to a different canned
    response per node -- the graph calls provider_for once per
    model-calling node it visits, so one resolver covers the whole run.
    """

    def _resolve(node_name: str) -> Any:
        return make_mock_provider(node_name=node_name, returns=returns_by_node[node_name])

    return _resolve


def _thread_config() -> RunnableConfig:
    return {"configurable": {"thread_id": str(uuid4())}}


async def test_graph_wine_happy_path_through_interrupt_and_resume(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    returns_by_node: dict[str, Any] = {
        "category_router": CategoryRouterOutput(suggested_category="wine", confidence=0.9),
        "identify": IdentifyOutput(
            best_guess="Beringer Founders' Estate Cabernet Sauvignon 2019", confidence=0.88
        ),
        "ocr": OcrOutput(
            state="text_present", text="BERINGER\nCABERNET SAUVIGNON\n2019", reason=None
        ),
        "generate_description_and_title": DescriptionOutput(
            title="Beringer Cabernet Sauvignon",
            description="A bottle of Beringer Cabernet Sauvignon, 2019.",
        ),
        "extract_structured": WineExtractionResult(
            fields=WineFields(producer="Beringer", varietal="Cabernet Sauvignon", vintage=2019),
            confidence_scores={"producer": 0.9, "varietal": 0.85, "vintage": 0.95},
        ),
    }
    monkeypatch.setattr(registry, "provider_for", _provider_resolver(returns_by_node))

    config = _thread_config()
    initial_state = GraphState(image=load_fixture("placeholder.png"), user_id=uuid4())

    paused = await compiled_graph.ainvoke(initial_state, config=config)

    # Graph paused at the await_category interrupt, per SPEC.md's contract:
    # router always pauses, no confidence threshold skips it.
    assert "__interrupt__" in paused
    interrupts = paused["__interrupt__"]
    assert len(interrupts) == 1
    assert interrupts[0].value == {"suggested_category": "wine", "confidence": 0.9}

    snapshot = await compiled_graph.aget_state(config)
    assert snapshot.next == ("await_category",)
    assert snapshot.values["suggested_category"] == "wine"
    # confirmed_category has a plain `= None` default (not
    # default_factory) and its channel has never been written yet (only
    # await_category writes it, on resume) -- LangGraph omits an
    # unwritten `None`-default channel from `values` entirely rather
    # than seeding it, so this is a missing key, not a `None` value.
    # See pipeline.py's docstring on node return values.
    assert snapshot.values.get("confirmed_category") is None

    # Resume with the user's confirmed category (accepting the suggestion).
    final = await compiled_graph.ainvoke(Command(resume="wine"), config=config)

    assert final["confirmed_category"] == "wine"
    assert final["title"] == "Beringer Cabernet Sauvignon"
    assert final["structured_fields"]["producer"] == "Beringer"
    assert final["structured_fields"]["vintage"] == 2019
    assert final["confidence_scores"]["producer"] == 0.9
    # validation_errors uses default_factory=list, unlike
    # confirmed_category above -- LangGraph seeds it from the factory up
    # front, so it's always present (starting as []), even before
    # validate's happy path leaves it untouched.
    assert final["validation_errors"] == []


async def test_graph_halloween_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    returns_by_node: dict[str, Any] = {
        "category_router": CategoryRouterOutput(suggested_category="halloween", confidence=0.8),
        "identify": IdentifyOutput(best_guess="a Funko Pop Jack Skellington", confidence=0.75),
        "ocr": OcrOutput(state="no_text", text="", reason="no_text"),
        "generate_description_and_title": DescriptionOutput(
            title="Jack Skellington Funko Pop",
            description="A Funko Pop figurine of Jack Skellington.",
        ),
        "extract_structured": HalloweenExtractionResult(
            fields=HalloweenFields(manufacturer="Funko", character_or_series="Jack Skellington"),
            confidence_scores={"manufacturer": 0.8, "character_or_series": 0.75},
        ),
    }
    monkeypatch.setattr(registry, "provider_for", _provider_resolver(returns_by_node))

    config = _thread_config()
    initial_state = GraphState(image=load_fixture("placeholder.png"), user_id=uuid4())

    await compiled_graph.ainvoke(initial_state, config=config)
    final = await compiled_graph.ainvoke(Command(resume="halloween"), config=config)

    assert final["confirmed_category"] == "halloween"
    assert final["structured_fields"]["manufacturer"] == "Funko"
    assert final["structured_fields"]["condition"] is None  # user-only, never AI-populated


async def test_graph_other_category_skips_extract_structured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    returns_by_node: dict[str, Any] = {
        "category_router": CategoryRouterOutput(suggested_category="other", confidence=0.4),
        "identify": IdentifyOutput(best_guess="a stapler", confidence=0.7),
        "ocr": OcrOutput(state="no_text", text="", reason="no_text"),
        "generate_description_and_title": DescriptionOutput(
            title="Stapler", description="A standard office stapler."
        ),
    }

    def _resolve(node_name: str) -> Any:
        if node_name == "extract_structured":
            pytest.fail("extract_structured should be skipped entirely for category 'other'")
        return make_mock_provider(node_name=node_name, returns=returns_by_node[node_name])

    monkeypatch.setattr(registry, "provider_for", _resolve)

    config = _thread_config()
    initial_state = GraphState(image=load_fixture("placeholder.png"), user_id=uuid4())

    await compiled_graph.ainvoke(initial_state, config=config)
    final = await compiled_graph.ainvoke(Command(resume="other"), config=config)

    assert final["confirmed_category"] == "other"
    # extract_structured never runs for "other" (conditional routing),
    # so structured_fields (a `= None`-default field) is never written --
    # absent, not None-valued.
    assert final.get("structured_fields") is None
    assert final["title"] == "Stapler"
    # validation_errors uses default_factory=list, so it's seeded and
    # present from the start regardless -- see the wine test above.
    assert final["validation_errors"] == []


async def test_graph_none_default_fields_stay_absent_until_written(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Regression coverage for a LangGraph mechanic behind the
    # partial-update fix in pipeline.py: GraphState fields with a plain
    # `= None` default (structured_fields, confirmed_category, ...) stay
    # entirely absent from ainvoke()/aget_state() output until some node
    # actually writes them. Fields with a `default_factory`
    # (confidence_scores, validation_errors) behave differently --
    # LangGraph seeds them from the factory up front, so they're always
    # present (starting as {} / []) even before any node writes to them.
    # Downstream consumers of the raw dict (the API layer, a later step)
    # need .get() for the first kind; GraphState.model_validate(result)
    # is the safe general-purpose way to hydrate a fully-defaulted
    # instance regardless of which kind a given field is.
    returns_by_node: dict[str, Any] = {
        "category_router": CategoryRouterOutput(suggested_category="other", confidence=0.4),
        "identify": IdentifyOutput(best_guess="a stapler", confidence=0.7),
        "ocr": OcrOutput(state="no_text", text="", reason="no_text"),
        "generate_description_and_title": DescriptionOutput(
            title="Stapler", description="A standard office stapler."
        ),
    }
    monkeypatch.setattr(registry, "provider_for", _provider_resolver(returns_by_node))

    config = _thread_config()
    initial_state = GraphState(image=load_fixture("placeholder.png"), user_id=uuid4())

    await compiled_graph.ainvoke(initial_state, config=config)
    final = await compiled_graph.ainvoke(Command(resume="other"), config=config)

    # None-default field, never written along the "other" path
    # (extract_structured never runs) -- absent.
    assert "structured_fields" not in final
    # default_factory fields -- seeded up front, always present.
    assert final["validation_errors"] == []
    assert final["confidence_scores"] == {}

    # GraphState.model_validate() hydrates either kind safely.
    hydrated = GraphState.model_validate(final)
    assert hydrated.structured_fields is None
    assert hydrated.validation_errors == []


async def test_graph_user_can_override_suggested_category(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # SPEC.md: the router's suggestion "can be accepted or overridden" --
    # the user's confirmed category is authoritative even when it
    # disagrees with what category_router suggested.
    returns_by_node: dict[str, Any] = {
        "category_router": CategoryRouterOutput(suggested_category="wine", confidence=0.55),
        "identify": IdentifyOutput(best_guess="a wine-themed Halloween decoration", confidence=0.6),
        "ocr": OcrOutput(state="no_text", text="", reason="no_text"),
        "generate_description_and_title": DescriptionOutput(
            title="Wine Bottle Decoration",
            description="A Halloween decoration shaped like a wine bottle.",
        ),
        "extract_structured": HalloweenExtractionResult(
            fields=HalloweenFields(manufacturer=None, character_or_series=None),
            confidence_scores={},
        ),
    }
    monkeypatch.setattr(registry, "provider_for", _provider_resolver(returns_by_node))

    config = _thread_config()
    initial_state = GraphState(image=load_fixture("placeholder.png"), user_id=uuid4())

    paused = await compiled_graph.ainvoke(initial_state, config=config)
    assert paused["__interrupt__"][0].value["suggested_category"] == "wine"

    # User overrides the router's "wine" suggestion with "halloween".
    final = await compiled_graph.ainvoke(Command(resume="halloween"), config=config)

    assert final["suggested_category"] == "wine"  # router's original suggestion, untouched
    assert final["confirmed_category"] == "halloween"  # user's override, authoritative
