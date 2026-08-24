"""Pydantic schemas for graph node inputs/outputs.

Centralized here rather than colocated with each node, so `state.py` and
every node module can import from one place without a circular
dependency: nodes import `GraphState` from `state.py`, and `state.py`
needs `IdentifyOutput`/`OcrOutput` to type its own fields.

These are node I/O contracts, distinct from `app/models/items.py`
(the persisted item schemas). `extract_structured`'s output schemas
below reuse `items.py`'s category-specific Literal types where it makes
sense (e.g. `HalloweenCondition`) but are otherwise separate models --
extraction output isn't a full `WineItem`/`HalloweenItem` (no `id`,
`user_id`, `title`, etc.).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.models.items import HalloweenCondition, WineType

Category = Literal["wine", "halloween", "other"]


class CategoryRouterOutput(BaseModel):
    """category_router's structured-output schema. See SPEC.md."""

    suggested_category: Category
    confidence: float = Field(ge=0.0, le=1.0)


class IdentifyOutput(BaseModel):
    """identify's structured-output schema. See SPEC.md."""

    best_guess: str
    confidence: float = Field(ge=0.0, le=1.0)


OcrState = Literal["text_present", "text_unreadable", "no_text"]
OcrReason = Literal["unreadable", "no_text"]


class OcrOutput(BaseModel):
    """ocr's structured-output schema -- the three-state contract in SPEC.md."""

    state: OcrState
    text: str
    reason: OcrReason | None = None


class DescriptionOutput(BaseModel):
    """generate_description_and_title's structured-output schema."""

    title: str
    description: str


class WineFields(BaseModel):
    """Category-specific fields extract_structured produces for wine.

    Mirrors WineItem (app/models/items.py) field-for-field -- see this
    module's docstring on why they're still separate models.
    """

    producer: str | None = None
    vintage: int | None = Field(default=None, ge=1800, le=2100)
    type: WineType | None = None
    varietal: str | None = None
    style: str | None = None
    region: str | None = None
    appellation: str | None = None
    country: str | None = None
    bottled_in: str | None = None
    bottle_size: str | None = None


class HalloweenFields(BaseModel):
    """Category-specific fields extract_structured produces for halloween."""

    manufacturer: str | None = None
    character_or_series: str | None = None
    year: int | None = Field(default=None, ge=1900, le=2100)
    edition: str | None = None
    condition: HalloweenCondition | None = None


class WineExtractionResult(BaseModel):
    """extract_structured's structured-output schema for wine items."""

    fields: WineFields
    confidence_scores: dict[str, float]


class HalloweenExtractionResult(BaseModel):
    """extract_structured's structured-output schema for halloween items."""

    fields: HalloweenFields
    confidence_scores: dict[str, float]
