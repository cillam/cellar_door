"""ocr -- transcribes visible text, or reports unreadable/no_text.

See SPEC.md's three-state ocr node contract.
"""

from __future__ import annotations

from app.graph.prompts.ocr import OCR_PROMPT
from app.graph.schemas import OcrOutput
from app.graph.state import GraphState
from app.providers import registry


async def ocr(state: GraphState) -> GraphState:
    provider = registry.provider_for("ocr")
    result = await provider.complete_structured(
        prompt=OCR_PROMPT,
        image=state.image,
        schema=OcrOutput,
    )
    return state.model_copy(update={"ocr_result": result})
