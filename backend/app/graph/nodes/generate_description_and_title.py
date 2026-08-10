"""generate_description_and_title -- combines identify + ocr into a title
and description.

Text-only (no image call) -- synthesizes from `identify_result` and
`ocr_result`, already on state from the parallel identify/ocr nodes that
ran before this one. See SPEC.md's node contract.
"""

from __future__ import annotations

from app.graph.prompts.generate_description_and_title import (
    GENERATE_DESCRIPTION_AND_TITLE_PROMPT,
)
from app.graph.schemas import DescriptionOutput
from app.graph.state import GraphState
from app.providers import registry


def _identify_summary(state: GraphState) -> str:
    if state.identify_result is None:
        return "No identification available."
    return (
        f"Best guess: {state.identify_result.best_guess} "
        f"(confidence {state.identify_result.confidence:.2f})"
    )


def _ocr_summary(state: GraphState) -> str:
    if state.ocr_result is None:
        return "No OCR result available."
    if state.ocr_result.state == "text_present":
        return f"Text present: {state.ocr_result.text!r}"
    return f"No usable text (state: {state.ocr_result.state}, reason: {state.ocr_result.reason})"


async def generate_description_and_title(state: GraphState) -> GraphState:
    provider = registry.provider_for("generate_description_and_title")
    prompt = GENERATE_DESCRIPTION_AND_TITLE_PROMPT.format(
        identify_summary=_identify_summary(state),
        ocr_summary=_ocr_summary(state),
    )
    result = await provider.complete_structured(
        prompt=prompt,
        schema=DescriptionOutput,
    )
    return state.model_copy(update={"title": result.title, "description": result.description})
