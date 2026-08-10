"""Unit tests for app.graph.nodes.generate_description_and_title."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.graph.nodes.generate_description_and_title import (
    generate_description_and_title,
)
from app.graph.schemas import DescriptionOutput, IdentifyOutput, OcrOutput
from app.graph.state import GraphState
from app.providers import registry
from tests.conftest import load_fixture, make_mock_provider


async def test_generate_description_incorporates_ocr_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canned = DescriptionOutput(
        title="Beringer Cabernet Sauvignon",
        description="A bottle of Beringer Founders' Estate Cabernet Sauvignon, "
        "labeled 2019, California, 750ml.",
    )
    mock = make_mock_provider(node_name="generate_description_and_title", returns=canned)
    monkeypatch.setattr(registry, "provider_for", lambda node_name: mock)

    state = GraphState(
        image=load_fixture("placeholder.png"),
        user_id=uuid4(),
        identify_result=IdentifyOutput(
            best_guess="Beringer Founders' Estate Cabernet Sauvignon 2019", confidence=0.88
        ),
        ocr_result=OcrOutput(
            state="text_present",
            text="BERINGER\nFOUNDERS' ESTATE\nCABERNET SAUVIGNON\n2019",
            reason=None,
        ),
    )
    result = await generate_description_and_title(state)

    assert result.title == "Beringer Cabernet Sauvignon"
    assert "Beringer" in (result.description or "")

    call = mock.calls[0]
    assert call.method == "complete_structured"
    assert call.schema is DescriptionOutput
    assert call.image is None  # text-only node, no vision call
    assert "Beringer Founders' Estate Cabernet Sauvignon 2019" in call.prompt
    assert "BERINGER" in call.prompt


async def test_generate_description_does_not_leak_fabricated_text_prompt_for_no_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canned = DescriptionOutput(
        title="Ceramic Pumpkin Figurine",
        description="A small ceramic pumpkin figurine with no visible markings.",
    )
    mock = make_mock_provider(node_name="generate_description_and_title", returns=canned)
    monkeypatch.setattr(registry, "provider_for", lambda node_name: mock)

    state = GraphState(
        image=load_fixture("placeholder.png"),
        user_id=uuid4(),
        identify_result=IdentifyOutput(
            best_guess="a small ceramic pumpkin figurine", confidence=0.4
        ),
        ocr_result=OcrOutput(state="no_text", text="", reason="no_text"),
    )
    result = await generate_description_and_title(state)

    assert result.title == "Ceramic Pumpkin Figurine"
    call = mock.calls[0]
    # The prompt tells the model there's no usable text, rather than an
    # empty string that could read as "nothing to say about text."
    assert "no usable text" in call.prompt.lower()
    assert "state: no_text" in call.prompt


async def test_generate_description_ocr_text_unreadable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The third leg of ocr's three-state contract (SPEC.md line 148) --
    # distinct from no_text, but _ocr_summary treats both as "no usable
    # text" for prompting purposes. Pinned down explicitly rather than
    # left to fall out of the no_text case by coincidence.
    canned = DescriptionOutput(
        title="Wine Bottle",
        description="A wine bottle with a label that couldn't be read clearly.",
    )
    mock = make_mock_provider(node_name="generate_description_and_title", returns=canned)
    monkeypatch.setattr(registry, "provider_for", lambda node_name: mock)

    state = GraphState(
        image=load_fixture("placeholder.png"),
        user_id=uuid4(),
        identify_result=IdentifyOutput(best_guess="a wine bottle", confidence=0.3),
        ocr_result=OcrOutput(state="text_unreadable", text="", reason="unreadable"),
    )
    result = await generate_description_and_title(state)

    assert result.title == "Wine Bottle"
    call = mock.calls[0]
    assert "no usable text" in call.prompt.lower()
    assert "state: text_unreadable" in call.prompt
    assert "reason: unreadable" in call.prompt


async def test_generate_description_handles_missing_identify_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Exercises _identify_summary's None branch directly. Unreachable via
    # the real graph (identify always runs first), but GraphState types
    # identify_result as Optional, so the explicit-handling path should
    # actually be covered rather than just present.
    canned = DescriptionOutput(title="Unknown Item", description="An unidentified item.")
    mock = make_mock_provider(node_name="generate_description_and_title", returns=canned)
    monkeypatch.setattr(registry, "provider_for", lambda node_name: mock)

    state = GraphState(
        image=load_fixture("placeholder.png"),
        user_id=uuid4(),
        identify_result=None,
        ocr_result=OcrOutput(state="no_text", text="", reason="no_text"),
    )
    result = await generate_description_and_title(state)

    assert result.title == "Unknown Item"
    assert "No identification available." in mock.calls[0].prompt


async def test_generate_description_handles_missing_ocr_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Exercises _ocr_summary's None branch directly -- same reasoning as
    # test_generate_description_handles_missing_identify_result above.
    canned = DescriptionOutput(title="Unknown Item", description="An unidentified item.")
    mock = make_mock_provider(node_name="generate_description_and_title", returns=canned)
    monkeypatch.setattr(registry, "provider_for", lambda node_name: mock)

    state = GraphState(
        image=load_fixture("placeholder.png"),
        user_id=uuid4(),
        identify_result=IdentifyOutput(best_guess="a small item", confidence=0.3),
        ocr_result=None,
    )
    result = await generate_description_and_title(state)

    assert result.title == "Unknown Item"
    assert "No OCR result available." in mock.calls[0].prompt
