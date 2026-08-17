"""GraphState -- the single Pydantic model threaded through every node.

Nodes are pure functions over GraphState: `(state: GraphState) -> GraphState`
(see CLAUDE.md and .claude/add-graph-node.md). Never mutate state in
place -- always return a new instance via `state.model_copy(update=...)`.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.graph.schemas import Category, IdentifyOutput, OcrOutput


class GraphState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Input, set when the graph starts.
    image: bytes
    user_id: UUID

    # Supabase Storage path the image was loaded from (POST
    # /items/from-photo's request body). Threaded through so the
    # `complete` event (app/routers/items.py) can populate
    # ItemDraft.photo_url without a second source of truth outside the
    # graph's own checkpointed state.
    storage_path: str | None = None

    # category_router's output, plus the user's confirmation after the
    # await_category interrupt. suggested_category/router_confidence are
    # the router's suggestion; confirmed_category is authoritative once
    # set (SPEC.md: "the user's confirmation is authoritative").
    suggested_category: Category | None = None
    router_confidence: float | None = None
    confirmed_category: Category | None = None

    # identify + ocr run in parallel after resume.
    identify_result: IdentifyOutput | None = None
    ocr_result: OcrOutput | None = None

    # generate_description_and_title's output, flattened onto state.
    title: str | None = None
    description: str | None = None

    # extract_structured's output. A flattened dict, not a typed model,
    # because the shape is category-dependent -- WineFields for wine,
    # HalloweenFields for halloween, absent entirely for "other".
    structured_fields: dict[str, Any] | None = None

    # Per-field confidence, populated by extract_structured and by
    # validate on failure (blanked fields get 0.0). Keys are field names.
    confidence_scores: dict[str, float] = Field(default_factory=dict)

    # validate's output: one message per Pydantic validation failure, for
    # user visibility (SPEC.md: "add the validation error to the response
    # payload for user visibility"). Empty when validation passed or
    # didn't run.
    validation_errors: list[str] = Field(default_factory=list)
