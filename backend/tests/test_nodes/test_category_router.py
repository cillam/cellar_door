"""Unit tests for app.graph.nodes.category_router."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.graph.nodes.category_router import category_router
from app.graph.schemas import CategoryRouterOutput
from app.graph.state import GraphState
from app.providers import registry
from tests.conftest import load_fixture, make_mock_provider


async def test_category_router_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    canned = CategoryRouterOutput(suggested_category="wine", confidence=0.94)
    mock = make_mock_provider(node_name="category_router", returns=canned)
    monkeypatch.setattr(registry, "provider_for", lambda node_name: mock)

    state = GraphState(image=load_fixture("placeholder.png"), user_id=uuid4())
    result = await category_router(state)

    assert result.suggested_category == "wine"
    assert result.router_confidence == 0.94
    assert len(mock.calls) == 1
    assert mock.calls[0].method == "complete_structured"
    assert mock.calls[0].schema is CategoryRouterOutput
    assert mock.calls[0].image == state.image


async def test_category_router_returns_new_state_without_mutating_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canned = CategoryRouterOutput(suggested_category="other", confidence=0.3)
    mock = make_mock_provider(node_name="category_router", returns=canned)
    monkeypatch.setattr(registry, "provider_for", lambda node_name: mock)

    state = GraphState(image=load_fixture("placeholder.png"), user_id=uuid4())
    result = await category_router(state)

    assert state.suggested_category is None  # original state untouched
    assert result is not state
    assert result.suggested_category == "other"
    assert result.router_confidence == 0.3
