"""Unit tests for app.graph.nodes.ocr -- covers the three-state contract."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.graph.nodes.ocr import ocr
from app.graph.schemas import OcrOutput
from app.graph.state import GraphState
from app.providers import registry
from tests.conftest import load_fixture, make_mock_provider


async def test_ocr_text_present(monkeypatch: pytest.MonkeyPatch) -> None:
    canned = OcrOutput(state="text_present", text="BERINGER\nCABERNET SAUVIGNON", reason=None)
    mock = make_mock_provider(node_name="ocr", returns=canned)
    monkeypatch.setattr(registry, "provider_for", lambda node_name: mock)

    state = GraphState(image=load_fixture("placeholder.png"), user_id=uuid4())
    result = await ocr(state)

    assert result.ocr_result is not None
    assert result.ocr_result.state == "text_present"
    assert result.ocr_result.text == "BERINGER\nCABERNET SAUVIGNON"
    assert result.ocr_result.reason is None
    assert mock.calls[0].schema is OcrOutput
    assert mock.calls[0].image == state.image


async def test_ocr_no_text(monkeypatch: pytest.MonkeyPatch) -> None:
    canned = OcrOutput(state="no_text", text="", reason="no_text")
    mock = make_mock_provider(node_name="ocr", returns=canned)
    monkeypatch.setattr(registry, "provider_for", lambda node_name: mock)

    state = GraphState(image=load_fixture("placeholder.png"), user_id=uuid4())
    result = await ocr(state)

    assert result.ocr_result is not None
    assert result.ocr_result.state == "no_text"
    assert result.ocr_result.text == ""
    assert result.ocr_result.reason == "no_text"


async def test_ocr_text_unreadable(monkeypatch: pytest.MonkeyPatch) -> None:
    canned = OcrOutput(state="text_unreadable", text="", reason="unreadable")
    mock = make_mock_provider(node_name="ocr", returns=canned)
    monkeypatch.setattr(registry, "provider_for", lambda node_name: mock)

    state = GraphState(image=load_fixture("placeholder.png"), user_id=uuid4())
    result = await ocr(state)

    assert result.ocr_result is not None
    assert result.ocr_result.state == "text_unreadable"
    assert result.ocr_result.text == ""
    assert result.ocr_result.reason == "unreadable"
