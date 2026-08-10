"""identify -- best-guess product identification with a confidence score.

See SPEC.md's identify node contract.
"""

from __future__ import annotations

from app.graph.prompts.identify import IDENTIFY_PROMPT
from app.graph.schemas import IdentifyOutput
from app.graph.state import GraphState
from app.providers import registry


async def identify(state: GraphState) -> GraphState:
    provider = registry.provider_for("identify")
    result = await provider.complete_structured(
        prompt=IDENTIFY_PROMPT,
        image=state.image,
        schema=IdentifyOutput,
    )
    return state.model_copy(update={"identify_result": result})
