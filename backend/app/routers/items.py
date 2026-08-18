"""Item routes. See SPEC.md's API contract.

Photo-capture flow (POST /items/from-photo + resume) landed in step 4d.
This step (4e) adds the first persistence endpoints: POST /items,
GET /items, GET /items/{id}. PATCH/DELETE /items/{id} land in 4f.

SSE payload shapes are hand-mapped per node (`_sse_event_for_update`)
rather than forwarding the graph's internal partial-update dicts
directly -- SPEC.md's wire format doesn't match GraphState's field
names 1:1 (e.g. `router_confidence` -> `confidence`,
`structured_fields` -> `fields`).

Known gap, flagged rather than silently resolved: SPEC.md's `validate`
node contract says to "add the validation error to the response
payload for user visibility," but `ItemDraft` (app/models/items.py,
human-edited only) has no `validation_errors` field. `_build_item_draft`
below builds exactly what ItemDraft's current schema supports, dropping
validation_errors rather than either inventing a field on a locked
schema or silently losing the requirement without saying so. See this
router's introducing PR for the full note.

Row <-> Item mapping (`_row_to_item`, `_insert_item`): base BaseItem
columns map directly; category-specific fields live in the `details`
JSONB column (the migration, step 4a). `_insert_item` computes
`details` as `item.model_dump(exclude=set(BaseItem.model_fields))` --
everything the subclass adds beyond BaseItem -- rather than
hand-listing wine/halloween fields, so a new category (ROADMAP.md)
needs no change here.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID, uuid4

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command, StateSnapshot
from pydantic import BaseModel

from app.auth import get_current_user_id
from app.db import get_db_pool
from app.graph.pipeline import compiled_graph
from app.graph.state import GraphState
from app.models.items import BaseItem, HalloweenItem, Item, ItemDraft, OtherItem, WineItem
from app.storage import StorageClient, get_storage_client

router = APIRouter(prefix="/items", tags=["items"])

# SPEC.md: await_category's ttl_seconds, and the resume endpoint's 410
# ("checkpoint older than 1 hour") threshold -- one constant, not two
# numbers that could drift apart.
CHECKPOINT_TTL_SECONDS = 3600


class FromPhotoRequest(BaseModel):
    storage_path: str


class ResumeRequest(BaseModel):
    category: Literal["wine", "halloween", "other"]


def _format_sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _sse_event_for_update(
    node_name: str, update: dict[str, Any]
) -> tuple[str, dict[str, Any]] | None:
    """Map a node's partial-state update to its SPEC.md SSE event shape.

    Returns None for updates with no direct client-facing event:
    `validate` folds into `complete` rather than getting its own event
    (SPEC.md's example stream has no `validate` event), and
    `await_category` is handled specially by the caller (it needs
    thread_id/ttl_seconds, which aren't part of its own state update).
    """
    if node_name == "category_router":
        return "category_router", {
            "suggested_category": update["suggested_category"],
            "confidence": update["router_confidence"],
        }
    if node_name == "identify":
        return "identify", update["identify_result"].model_dump(mode="json")
    if node_name == "ocr":
        return "ocr", update["ocr_result"].model_dump(mode="json")
    if node_name == "generate_description_and_title":
        return "generate_description_and_title", {
            "title": update["title"],
            "description": update["description"],
        }
    if node_name == "extract_structured":
        return "extract_structured", {
            "fields": update.get("structured_fields"),
            "confidence_scores": update.get("confidence_scores", {}),
        }
    return None


def _build_item_draft(state: GraphState) -> ItemDraft:
    """The `complete` event's payload -- SPEC.md: "full ItemDraft
    payload, unsaved, id=null".

    Nested wine/halloween/other sub-items get a real user_id (known
    from the JWT) and an auto-generated id/created_at/updated_at
    (ItemDraft's own docstring: those aren't meaningful pre-save --
    POST /items server-assigns the real ones and ignores whatever the
    client sends back).
    """
    category = state.confirmed_category
    if category is None or state.storage_path is None:
        # Unreachable via the real graph -- confirmed_category is set
        # by await_category before any of the nodes that lead here run,
        # and storage_path is set at graph invocation. Guarded anyway
        # per CLAUDE.md's explicit-None-handling rule.
        raise ValueError("_build_item_draft called before confirmed_category/storage_path were set")

    title = state.title or ""
    description = state.description or ""
    common: dict[str, Any] = {
        "user_id": state.user_id,
        "photo_url": state.storage_path,
        "title": title,
        "description": description,
        "confidence_scores": state.confidence_scores,
    }
    fields = state.structured_fields or {}

    wine: WineItem | None = None
    halloween: HalloweenItem | None = None
    other: OtherItem | None = None
    if category == "wine":
        wine = WineItem(**common, **fields)
    elif category == "halloween":
        halloween = HalloweenItem(**common, **fields)
    else:
        other = OtherItem(**common)

    return ItemDraft(
        category=category,
        photo_url=state.storage_path,
        title=title,
        description=description,
        confidence_scores=state.confidence_scores,
        wine=wine,
        halloween=halloween,
        other=other,
    )


async def _stream_from_photo(image: bytes, user_id: UUID, storage_path: str) -> AsyncIterator[str]:
    thread_id = str(uuid4())
    yield _format_sse("session", {"thread_id": thread_id})

    config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
    initial_state = GraphState(image=image, user_id=user_id, storage_path=storage_path)

    async for item in compiled_graph.astream(initial_state, config=config, stream_mode="updates"):
        if "__interrupt__" in item:
            break
        node_name, update = next(iter(item.items()))
        sse_event = _sse_event_for_update(node_name, update)
        if sse_event is not None:
            yield _format_sse(*sse_event)

    snapshot = await compiled_graph.aget_state(config)
    yield _format_sse(
        "await_category",
        {
            "thread_id": thread_id,
            "suggested_category": snapshot.values.get("suggested_category"),
            "confidence": snapshot.values.get("router_confidence"),
            "ttl_seconds": CHECKPOINT_TTL_SECONDS,
        },
    )


@router.post("/from-photo")
async def from_photo(
    request: FromPhotoRequest,
    user_id: UUID = Depends(get_current_user_id),
    storage_client: StorageClient = Depends(get_storage_client),
) -> StreamingResponse:
    # SPEC.md Auth: verify the path belongs to this user *before*
    # loading the image or running the pipeline.
    if not request.storage_path.startswith(f"photos/{user_id}/"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="storage_path does not belong to the authenticated user",
        )

    try:
        image = await storage_client.download(request.storage_path)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Photo not found"
        ) from exc

    return StreamingResponse(
        _stream_from_photo(image, user_id, request.storage_path),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )


async def _load_snapshot_for_resume(
    thread_id: str, user_id: UUID, *, now: datetime | None = None
) -> StateSnapshot:
    """`now` is a testing seam, not something the HTTP layer ever
    exposes -- the resume endpoint always calls this with the real
    current time. Tests inject a future `now` to exercise the 410 path
    without literally waiting an hour ("a time-advancing fixture").
    """
    config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
    snapshot = await compiled_graph.aget_state(config)

    # Nonexistent thread_id -> empty values -> no user_id key at all.
    # Same response as a real mismatch (SPEC.md Auth: "Mismatches
    # return 403 ... they're just not authorized" -- don't distinguish
    # "doesn't exist" from "exists but isn't yours").
    snapshot_user_id = snapshot.values.get("user_id")
    if snapshot_user_id is None or snapshot_user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="thread_id does not belong to the authenticated user",
        )

    # Checked before expiry: a resumed thread's TTL is moot. Our graph
    # has exactly one interrupt, so any next() other than
    # ("await_category",) means resume already happened.
    if snapshot.next != ("await_category",):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Graph has already been resumed"
        )

    if snapshot.created_at is not None:
        created_at = datetime.fromisoformat(snapshot.created_at)
        current_time = now or datetime.now(created_at.tzinfo or UTC)
        age = current_time - created_at
        if age > timedelta(seconds=CHECKPOINT_TTL_SECONDS):
            raise HTTPException(status_code=status.HTTP_410_GONE, detail="Checkpoint has expired")

    return snapshot


async def _stream_resume(thread_id: str, category: str) -> AsyncIterator[str]:
    config: RunnableConfig = {"configurable": {"thread_id": thread_id}}

    async for item in compiled_graph.astream(
        Command(resume=category), config=config, stream_mode="updates"
    ):
        if "__interrupt__" in item:
            continue  # unreachable -- the graph has exactly one interrupt
        node_name, update = next(iter(item.items()))
        sse_event = _sse_event_for_update(node_name, update)
        if sse_event is not None:
            yield _format_sse(*sse_event)

    final_snapshot = await compiled_graph.aget_state(config)
    final_state = GraphState.model_validate(final_snapshot.values)
    draft = _build_item_draft(final_state)
    yield _format_sse("complete", draft.model_dump(mode="json"))


@router.post("/from-photo/{thread_id}/resume")
async def resume_from_photo(
    thread_id: str,
    request: ResumeRequest,
    user_id: UUID = Depends(get_current_user_id),
) -> StreamingResponse:
    await _load_snapshot_for_resume(thread_id, user_id)

    return StreamingResponse(
        _stream_resume(thread_id, request.category),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )


_BASE_COLUMNS = (
    "id",
    "user_id",
    "category",
    "photo_url",
    "title",
    "description",
    "notes",
    "estimated_value",
    "confidence_scores",
    "created_at",
    "updated_at",
)


def _row_to_item(row: Mapping[str, Any]) -> Item:
    """Reconstruct an Item from an `items` table row.

    Base columns map directly; `details` (JSONB, category-specific
    fields) gets spread on top -- WineFields/HalloweenFields' field
    names match WineItem/HalloweenItem's own field names exactly (see
    app/graph/schemas.py), so this needs no per-field translation.
    """
    base: dict[str, Any] = {column: row[column] for column in _BASE_COLUMNS}
    details = row["details"] or {}
    category = row["category"]
    if category == "wine":
        return WineItem(**base, **details)
    if category == "halloween":
        return HalloweenItem(**base, **details)
    return OtherItem(**base)


async def _insert_item(pool: asyncpg.Pool, item: Item, user_id: UUID) -> asyncpg.Record:
    """Insert `item`, server-assigning id/user_id -- SPEC.md: "Server
    assigns id and user_id; client-provided values are ignored."
    created_at/updated_at come from the table's own defaults (now()),
    not whatever the client sent.
    """
    details = item.model_dump(mode="json", exclude=set(BaseItem.model_fields))
    row = await pool.fetchrow(
        """
        INSERT INTO items (
            id, user_id, category, photo_url, title, description,
            notes, estimated_value, confidence_scores, details
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
        RETURNING *
        """,
        uuid4(),
        user_id,
        item.category,
        item.photo_url,
        item.title,
        item.description,
        item.notes,
        item.estimated_value,
        item.confidence_scores,
        details,
    )
    if row is None:
        raise RuntimeError("INSERT ... RETURNING * returned no row")
    return row


@router.post("/", response_model=Item, status_code=status.HTTP_201_CREATED)
async def create_item(
    item: Item,
    user_id: UUID = Depends(get_current_user_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
) -> Item:
    row = await _insert_item(pool, item, user_id)
    return _row_to_item(row)


@router.get("/", response_model=list[Item])
async def list_items(
    user_id: UUID = Depends(get_current_user_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
) -> list[Item]:
    """SPEC.md: "array of the user's items, newest first by created_at"."""
    rows = await pool.fetch(
        "SELECT * FROM items WHERE user_id = $1 ORDER BY created_at DESC", user_id
    )
    return [_row_to_item(row) for row in rows]


@router.get("/{item_id}", response_model=Item)
async def get_item(
    item_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
) -> Item:
    row = await pool.fetchrow(
        "SELECT * FROM items WHERE id = $1 AND user_id = $2", item_id, user_id
    )
    if row is None:
        # Same response whether the item doesn't exist or belongs to
        # another user -- matches PATCH/DELETE's documented behavior
        # (SPEC.md), extended here to GET for consistency. Distinct
        # from the 403 pattern used when a resource identifier is in
        # the *request body* (POST /items/from-photo's storage_path,
        # resume's thread_id) -- see this file's module docstring.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")
    return _row_to_item(row)
