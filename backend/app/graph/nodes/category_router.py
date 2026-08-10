"""category_router -- suggests wine/halloween/other with a confidence score.

See SPEC.md's category_router node contract. The graph always pauses
after this node for user confirmation (the await_category interrupt,
wired in app/graph/pipeline.py) -- the router's suggestion is never
authoritative on its own.
"""

from __future__ import annotations

from app.graph.prompts.category_router import CATEGORY_ROUTER_PROMPT
from app.graph.schemas import CategoryRouterOutput
from app.graph.state import GraphState
from app.providers import registry


async def category_router(state: GraphState) -> GraphState:
    provider = registry.provider_for("category_router")
    result = await provider.complete_structured(
        prompt=CATEGORY_ROUTER_PROMPT,
        image=state.image,
        schema=CategoryRouterOutput,
    )
    return state.model_copy(
        update={
            "suggested_category": result.suggested_category,
            "router_confidence": result.confidence,
        }
    )
