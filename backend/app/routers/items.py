"""Item routes. See SPEC.md's API contract.

Photo-capture flow (POST /items/from-photo + resume) landed in step 4d.
Step 4e added POST /items, GET /items, GET /items/{id}. This step (4f)
adds PATCH/DELETE /items/{id}, closing out step 4.

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
import logging
from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID, uuid4

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command, StateSnapshot
from pydantic import BaseModel, ValidationError

from app.auth import get_current_user_id
from app.db import get_db_pool
from app.graph.pipeline import compiled_graph
from app.graph.state import GraphState
from app.models.items import BaseItem, HalloweenItem, Item, ItemDraft, OtherItem, WineItem
from app.storage import StorageClient, get_storage_client

logger = logging.getLogger(__name__)

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

# category -> the concrete Item subclass. Shared by _row_to_item (DB row
# -> typed item) and update_item (validating a PATCH's merged result
# against the right subclass) rather than each hand-rolling the same
# wine/halloween/other dispatch.
_ITEM_CLASSES: dict[str, type[WineItem] | type[HalloweenItem] | type[OtherItem]] = {
    "wine": WineItem,
    "halloween": HalloweenItem,
    "other": OtherItem,
}

# SPEC.md PATCH /items/{id}: these six fields "are immutable after save
# and cannot be changed via PATCH ... returns 400." Everything else
# (title, description, notes, estimated_value, category-specific
# fields) is mutable.
_IMMUTABLE_FIELDS = frozenset(
    {"id", "user_id", "category", "photo_url", "created_at", "confidence_scores"}
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
    item_class = _ITEM_CLASSES[row["category"]]
    return item_class(**base, **details)


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


@router.post("", response_model=Item, status_code=status.HTTP_201_CREATED)
async def create_item(
    item: Item,
    user_id: UUID = Depends(get_current_user_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
) -> Item:
    # Same check as POST /items/from-photo's storage_path -- item.photo_url
    # is a free-text field on the request body, and without this a
    # client could save another user's photos/<other-user-id>/... path
    # and later have a signed *read* URL generated for it.
    if not item.photo_url.startswith(f"photos/{user_id}/"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="photo_url does not belong to the authenticated user",
        )
    row = await _insert_item(pool, item, user_id)
    return _row_to_item(row)


@router.get("", response_model=list[Item])
async def list_items(
    user_id: UUID = Depends(get_current_user_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
) -> list[Item]:
    """SPEC.md: "array of the user's items, newest first by created_at"."""
    rows = await pool.fetch(
        "SELECT * FROM items WHERE user_id = $1 ORDER BY created_at DESC", user_id
    )
    return [_row_to_item(row) for row in rows]


async def _fetch_owned_item_row(pool: asyncpg.Pool, item_id: UUID, user_id: UUID) -> asyncpg.Record:
    """SELECT a row this user owns, or 404.

    Same response whether the item doesn't exist or belongs to another
    user -- matches PATCH/DELETE's documented SPEC.md behavior, and
    GET /items/{id} for consistency. Distinct from the 403 pattern used
    when a resource identifier is in the *request body* (POST
    /items/from-photo's storage_path, resume's thread_id) -- see this
    file's module docstring.
    """
    row = await pool.fetchrow(
        "SELECT * FROM items WHERE id = $1 AND user_id = $2", item_id, user_id
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")
    return row


@router.get("/{item_id}", response_model=Item)
async def get_item(
    item_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
) -> Item:
    row = await _fetch_owned_item_row(pool, item_id, user_id)
    return _row_to_item(row)


_MUTABLE_SCALAR_COLUMNS = frozenset({"title", "description", "notes", "estimated_value"})


@router.patch("/{item_id}", response_model=Item)
async def update_item(
    item_id: UUID,
    # dict[str, Any], not a typed Pydantic model like create_item's `item:
    # Item` -- deliberate. A typed all-Optional patch model would get
    # FastAPI's automatic 422 on a bad field type before this function
    # even runs, which would fight the uniform 400 behavior SPEC.md wants
    # here (immutable-field attempts and shape errors both -> 400, via
    # the manual re-validation below). Costs the OpenAPI schema some
    # precision (patch is just `object` today) -- worth revisiting once
    # mobile/'s generated client needs real field-level types for this.
    patch: dict[str, Any],
    user_id: UUID = Depends(get_current_user_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
) -> Item:
    """SPEC.md: partial update; id/user_id/category/photo_url/created_at/
    confidence_scores are immutable (400 on an attempt to change any of
    them); everything else (title, description, notes, estimated_value,
    category-specific fields) is mutable. updated_at is refreshed
    server-side on every successful PATCH.
    """
    attempted_immutable = sorted(_IMMUTABLE_FIELDS & patch.keys())
    if attempted_immutable:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot change immutable field(s): {', '.join(attempted_immutable)}",
        )

    existing_row = await _fetch_owned_item_row(pool, item_id, user_id)
    existing_item = _row_to_item(existing_row)

    # Merge onto the existing item's full field set, then re-validate
    # against its concrete subclass -- catches bad types/unknown fields
    # in the patch (extra="forbid") the same way construction would.
    # This merged snapshot is for *validation* only -- the UPDATE below
    # writes only the fields actually present in `patch`, not this
    # snapshot's values for fields the patch never touched (see its
    # docstring for why that distinction matters).
    merged = existing_item.model_dump(mode="json")
    merged.update(patch)
    try:
        updated_item = _ITEM_CLASSES[existing_item.category].model_validate(merged)
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    row = await _apply_item_patch(pool, item_id, user_id, patch, updated_item)
    if row is None:
        # The item existed at _fetch_owned_item_row above but is gone
        # now -- e.g. deleted by a concurrent request in between. 404,
        # not a 500: from the client's perspective this is the same
        # "not found" as if it had never existed.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")
    return _row_to_item(row)


async def _apply_item_patch(
    pool: asyncpg.Pool,
    item_id: UUID,
    user_id: UUID,
    patch: dict[str, Any],
    updated_item: Item,
) -> asyncpg.Record | None:
    """UPDATE only the columns `patch` actually touched, using
    `updated_item`'s already-validated values for them.

    Deliberately *not* an unconditional rewrite of every mutable column
    from a pre-fetched snapshot (update_item's earlier revision did
    this): two concurrent PATCHes touching different fields on the same
    item would otherwise race -- whichever UPDATE commits last
    overwrites the other's change with its own stale read of the field
    it wasn't even touching. Scalar columns (title/description/notes/
    estimated_value) get a plain column-level SET; category-specific
    fields get merged into the `details` JSONB column via Postgres's
    `||` operator, which is itself atomic and only touches the
    top-level keys given -- no read of the current `details` needed.
    """
    set_clauses = ["updated_at = now()"]
    params: list[Any] = [item_id, user_id]

    for field in patch:
        if field in _MUTABLE_SCALAR_COLUMNS:
            params.append(getattr(updated_item, field))
            set_clauses.append(f"{field} = ${len(params)}")

    detail_updates = {
        field: getattr(updated_item, field)
        for field in patch
        if field not in _IMMUTABLE_FIELDS and field not in _MUTABLE_SCALAR_COLUMNS
    }
    if detail_updates:
        # Pass the raw dict, not json.dumps(detail_updates) -- the pool's
        # registered jsonb codec (app/db.py) already encodes outgoing
        # jsonb parameters. Encoding it here too double-encodes into a
        # jsonb *string*, and `object || string` in Postgres produces a
        # jsonb array, not a merged object (caught by
        # test_update_item_category_specific_field_succeeds).
        params.append(detail_updates)
        set_clauses.append(f"details = details || ${len(params)}::jsonb")

    # set_clauses is built from fixed column names in a closed set
    # (_MUTABLE_SCALAR_COLUMNS, "details", "updated_at"), never from
    # patch's keys or values directly -- all real values are bound
    # params ($1, $2, ...), not interpolated into the query string.
    query = f"""
        UPDATE items
        SET {", ".join(set_clauses)}
        WHERE id = $1 AND user_id = $2
        RETURNING *
    """
    return await pool.fetchrow(query, *params)


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_item(
    item_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    storage_client: StorageClient = Depends(get_storage_client),
) -> None:
    """SPEC.md: 204 on success, 404 on missing/cross-user (same
    response for both); also deletes the photo from Supabase Storage.
    """
    row = await pool.fetchrow(
        "DELETE FROM items WHERE id = $1 AND user_id = $2 RETURNING photo_url",
        item_id,
        user_id,
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")

    # Best-effort: the item is already gone from the DB (the source of
    # truth for GET /items), so a storage-side failure shouldn't turn a
    # successful delete into an error response. Logged, not silently
    # swallowed, so a real outage is still visible somewhere.
    try:
        await storage_client.delete(row["photo_url"])
    except Exception:
        logger.warning(
            "Failed to delete photo %s for item %s", row["photo_url"], item_id, exc_info=True
        )
