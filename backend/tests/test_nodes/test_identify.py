"""Unit tests for app.graph.nodes.identify."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.graph.nodes.identify import identify
from app.graph.schemas import IdentifyOutput
from app.graph.state import GraphState
from app.providers import registry
from tests.conftest import load_fixture, make_mock_provider


async def test_identify_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    canned = IdentifyOutput(
        best_guess="Beringer Founders' Estate Cabernet Sauvignon 2019", confidence=0.88
    )
    mock = make_mock_provider(node_name="identify", returns=canned)
    monkeypatch.setattr(registry, "provider_for", lambda node_name: mock)

    state = GraphState(image=load_fixture("placeholder.png"), user_id=uuid4())
    result = await identify(state)

    assert result.identify_result is not None
    assert result.identify_result.best_guess == "Beringer Founders' Estate Cabernet Sauvignon 2019"
    assert result.identify_result.confidence == 0.88
    assert mock.calls[0].schema is IdentifyOutput
    assert mock.calls[0].image == state.image


async def test_identify_low_confidence_generic_guess(monkeypatch: pytest.MonkeyPatch) -> None:
    # SPEC.md: below 0.5 confidence, the guess should be generic and
    # grounded in visible features, not a hedged specific guess.
    canned = IdentifyOutput(best_guess="a tall dark green wine bottle", confidence=0.3)
    mock = make_mock_provider(node_name="identify", returns=canned)
    monkeypatch.setattr(registry, "provider_for", lambda node_name: mock)

    state = GraphState(image=load_fixture("placeholder.png"), user_id=uuid4())
    result = await identify(state)

    assert result.identify_result is not None
    assert result.identify_result.confidence < 0.5
    assert "possibly" not in result.identify_result.best_guess.lower()
