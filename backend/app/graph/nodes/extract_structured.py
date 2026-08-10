"""extract_structured -- category-specific field extraction with
evidence-grounded null handling.

See SPEC.md's node contract. Vision + OCR context: the model sees the
photo directly (for e.g. reading a vintage numeral precisely) and the
already-transcribed OCR text (for cross-referencing what it reads
against verbatim text), rather than relying on either alone.

Skipped for "other" -- app/graph/pipeline.py routes around this node
entirely for that category via a conditional edge, so this function
isn't even called for "other" in the real graph. Still defensive about
confirmed_category being unset/other if called directly, per CLAUDE.md's
None-handling rule for node inputs.
"""

from __future__ import annotations

from app.graph.prompts.extract_structured import (
    HALLOWEEN_EXTRACTION_PROMPT,
    WINE_EXTRACTION_PROMPT,
)
from app.graph.schemas import (
    HalloweenExtractionResult,
    HalloweenFields,
    WineExtractionResult,
    WineFields,
)
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


async def extract_structured(state: GraphState) -> GraphState:
    if state.confirmed_category not in ("wine", "halloween"):
        # "other" has no category-specific fields; anything else means
        # this ran before confirmation, which the graph's conditional
        # routing shouldn't allow. Skip rather than guess.
        return state

    provider = registry.provider_for("extract_structured")
    identify_summary = _identify_summary(state)
    ocr_summary = _ocr_summary(state)

    fields: WineFields | HalloweenFields
    confidence_scores: dict[str, float]
    if state.confirmed_category == "wine":
        wine_result = await provider.complete_structured(
            prompt=WINE_EXTRACTION_PROMPT.format(
                identify_summary=identify_summary, ocr_summary=ocr_summary
            ),
            image=state.image,
            schema=WineExtractionResult,
        )
        fields = wine_result.fields
        confidence_scores = wine_result.confidence_scores
    else:
        halloween_result = await provider.complete_structured(
            prompt=HALLOWEEN_EXTRACTION_PROMPT.format(
                identify_summary=identify_summary, ocr_summary=ocr_summary
            ),
            image=state.image,
            schema=HalloweenExtractionResult,
        )
        # condition is schema-permitted but prompt-discouraged only --
        # HalloweenFields doesn't exclude it structurally, and the model
        # can ignore "do not populate condition." SPEC.md and items.py
        # are explicit that condition is a user judgment call, never
        # AI-populated, so force it here rather than trust compliance.
        fields = halloween_result.fields.model_copy(update={"condition": None})
        confidence_scores = halloween_result.confidence_scores

    return state.model_copy(
        update={
            "structured_fields": fields.model_dump(),
            "confidence_scores": {**state.confidence_scores, **confidence_scores},
        }
    )
