"""
Pydantic schemas for inventory items.

This module is the single source of truth for item shapes across:
  - DB serialization (via SQLAlchemy ItemRow → these models)
  - Claude structured output (via `.with_structured_output()`)
  - API request/response bodies (FastAPI routes)
  - Mobile types (via openapi-typescript generation)

Changing a schema here cascades through DB serialization, Claude
structured output, API contracts, mobile types, eval fixtures, and tests.
The agent does not modify these classes without explicit human instruction.

Conventions:
  - Every category-specific field is nullable. The extraction pipeline
    returns None when a field isn't visible on the item. Never allow
    the model to invent a value — enforced by prompts + validation node.
  - `category` is the discriminator. Never change its value after
    construction; create a new instance instead.
  - `confidence_scores` is a flat dict keyed by field name with float
    values in [0.0, 1.0]. Used by the UI to highlight low-confidence
    fields for user verification.
  - `notes` is the escape valve for anything the structured schema
    doesn't capture. Always user-written, never AI-populated.

Adding a new category: see .claude/add-item-category.md
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------


class BaseItem(BaseModel):
    """Fields common to every inventory item, regardless of category.

    Subclasses add category-specific fields and override the `category`
    discriminator with a concrete Literal value.
    """

    model_config = ConfigDict(
        # Forbid extra fields — catches both agent hallucinations and
        # stale mobile clients sending fields the backend doesn't know.
        extra="forbid",
        # Pydantic v2: validate defaults so nullable-with-default fields
        # still get type-checked.
        validate_default=True,
    )

    id: UUID = Field(default_factory=uuid4)
    user_id: UUID
    category: str  # overridden by subclasses with a Literal
    title: str = Field(
        description="Short display name (≤5 words), shown in the "
        "inventory list and as the item detail header. Produced by "
        "`generate_description_and_title` alongside the description; user-editable "
        "on the form.",
    )
    photo_url: str = Field(
        description="Supabase Storage path (not a full URL). Signed URLs are generated on read."
    )
    description: str = Field(
        description="AI-generated, user-editable prose description. "
        "Always present; may be empty string if description node skipped."
    )
    notes: str | None = Field(
        default=None,
        description="User free-text escape valve for anything the "
        "structured schema doesn't capture. Never AI-populated.",
    )
    estimated_value: Decimal | None = Field(
        default=None,
        description="User-entered estimated value. MVP does not do "
        "price lookup against external APIs.",
    )
    confidence_scores: dict[str, float] = Field(
        default_factory=dict,
        description="Per-field confidence in [0.0, 1.0] from the "
        "extraction node. UI flags fields with low confidence for "
        "user verification. Keys are field names of this model.",
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# Wine
# ---------------------------------------------------------------------------


WineType = Literal["red", "white", "rose", "sparkling", "dessert", "fortified"]


class WineItem(BaseItem):
    """A bottle of wine."""

    category: Literal["wine"] = "wine"

    producer: str | None = Field(
        default=None,
        description="Winery or producer name as printed on the label. "
        "E.g., 'Beringer', 'Domaine de la Romanée-Conti'.",
    )
    vintage: int | None = Field(
        default=None,
        ge=1800,
        le=2100,
        description="Vintage year as a 4-digit integer. Null if not "
        "visible on the label (non-vintage wines, stylized numerals "
        "the model can't read confidently). Never guess.",
    )
    type: WineType | None = Field(
        default=None,
        description="Broad wine category. E.g., 'red', 'sparkling'.",
    )
    varietal: str | None = Field(
        default=None,
        description="Grape variety or blend name. E.g., 'Cabernet "
        "Sauvignon', 'Pinot Noir', 'Blend'. May be null for old-world "
        "wines where the label shows the appellation instead of the "
        "grape -- see the extraction contract's monovarietal-appellation "
        "exception.",
    )
    style: str | None = Field(
        default=None,
        description="Sweetness or house style within a type. E.g., "
        "'Brut', 'Reserve Brut', 'Demi-Sec', 'Dry', 'Late Harvest', "
        "'Ruby', 'Tawny'.",
    )
    region: str | None = Field(
        default=None,
        description="Broad geographic area the wine comes from. E.g., "
        "'Napa Valley', 'Burgundy', 'Champagne', 'Bordeaux'.",
    )
    appellation: str | None = Field(
        default=None,
        description="Specific identifier for the wine within its "
        "region -- a formal legal designation (AVA, AOC, DOCG, DOP) "
        "or a widely-recognized sub-region within regions whose "
        "sub-regions aren't formal appellations. E.g., 'St. Helena "
        "AVA', 'Bâtard-Montrachet', 'Chablis Grand Cru', 'Barolo "
        "DOCG', 'Côte des Bar' for Champagne. Named vineyards, crus, "
        "and specific plots (Les Clos, Cannubi) do NOT go here -- "
        "those belong in the description.",
    )
    country: str | None = Field(
        default=None,
        description="Country of origin. Always the full name, never "
        "an abbreviation -- 'United States' (not 'USA' or 'US'), "
        "'France'. May be inferable from the region even if not "
        "printed directly. Consistency matters: a user filtering "
        "their collection by country needs every wine from the same "
        "country to use the identical string.",
    )
    bottled_in: str | None = Field(
        default=None,
        description="City or municipality of the bottling facility, "
        "from the 'produced and bottled by' line on the label. E.g., "
        "'Épernay, France', 'St. Helena, California'. Never inferred "
        "from region -- a wine from Napa Valley wasn't necessarily "
        "bottled in Napa Valley.",
    )
    bottle_size: str | None = Field(
        default=None,
        description="Bottle volume as printed. E.g., '750ml', '1.5L', "
        "'375ml'. Null if not visible.",
    )


# ---------------------------------------------------------------------------
# Halloween
# ---------------------------------------------------------------------------


HalloweenCondition = Literal["mint", "good", "fair", "poor"]


class HalloweenItem(BaseItem):
    """A Halloween collectible — figurine, decoration, memorabilia, etc."""

    category: Literal["halloween"] = "halloween"

    manufacturer: str | None = Field(
        default=None,
        description="Manufacturer or brand name. E.g., 'Funko', "
        "'Hallmark', 'Department 56', 'Sun Hill'. Often on a sticker, "
        "tag, or box rather than the item itself.",
    )
    character_or_series: str | None = Field(
        default=None,
        description="Character or series name. E.g., 'Jack Skellington', "
        "'The Nightmare Before Christmas', 'Ghostbusters', 'Michael "
        "Myers'. For generic items (a plain ceramic pumpkin), null.",
    )
    year: int | None = Field(
        default=None,
        ge=1900,
        le=2100,
        description="Production or release year if printed on the "
        "item or packaging. Null if not visible. Do not infer from "
        "character/series — a 2023 figurine of a 1988 movie is from "
        "2023, not 1988.",
    )
    edition: str | None = Field(
        default=None,
        description="Edition designation as printed. E.g., 'Limited "
        "Edition', 'Convention Exclusive', 'Chase Variant', "
        "'Standard'. Null if no edition info visible.",
    )
    condition: HalloweenCondition | None = Field(
        default=None,
        description="Physical condition assessment. The AI should "
        "leave this null on first extraction — condition is a "
        "user judgment call, not a visual-AI one.",
    )


# ---------------------------------------------------------------------------
# Other
# ---------------------------------------------------------------------------
class OtherItem(BaseItem):
    """Catch-all for items that don't fit wine or halloween categories."""

    category: Literal["other"] = "other"


# ---------------------------------------------------------------------------
# Discriminated union
# ---------------------------------------------------------------------------


# The canonical Item type used throughout the codebase. Pydantic parses
# the correct subclass based on the `category` discriminator.
#
# Adding a new category:
#   1. Add the new class inheriting from BaseItem with a Literal category
#   2. Add it to the Union below
#   3. Update .claude/add-item-category.md if the steps change
Item = Annotated[
    WineItem | HalloweenItem | OtherItem,
    Field(discriminator="category"),
]


# ---------------------------------------------------------------------------
# Helper: the draft shape returned by /items/from-photo before user save
# ---------------------------------------------------------------------------


class ItemDraft(BaseModel):
    """The prefilled-but-unsaved result of running the extraction pipeline.

    Distinct from Item because:
      - `id` and `user_id` may not be set yet (user_id comes from the JWT,
        so it IS known server-side, but we keep the types separate so the
        "is this saved?" distinction is clear at the type level)
      - Category may be "unknown" for items the router couldn't classify
      - The user may edit any field before saving

    On save, the mobile app POSTs a full Item (not a draft), and the
    backend's save handler constructs it from the draft + user edits.
    """

    model_config = ConfigDict(extra="forbid")

    category: Literal["wine", "halloween", "other"]
    photo_url: str
    title: str
    description: str
    confidence_scores: dict[str, float] = Field(default_factory=dict)

    # Category-specific fields, all optional. The mobile form picks which
    # subset to render based on category.
    wine: WineItem | None = None
    halloween: HalloweenItem | None = None
    other: OtherItem | None = None
