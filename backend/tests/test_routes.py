"""Route tests for backend/app/main.py and backend/app/routers/.

All items.py's tests share this file per CLAUDE.md's directory
convention (one tests/test_routes.py, not one per router).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph.state import CompiledStateGraph

from app.graph.pipeline import build_graph, get_compiled_graph
from app.graph.schemas import (
    CategoryRouterOutput,
    DescriptionOutput,
    IdentifyOutput,
    OcrOutput,
    WineExtractionResult,
    WineFields,
)
from app.graph.state import GraphState
from app.main import app, docs_urls
from app.providers import registry
from app.routers.items import CHECKPOINT_TTL_SECONDS, _load_snapshot_for_resume
from app.storage import get_storage_client
from tests.conftest import (
    bearer_header,
    database_urls_pointed_at,
    make_mock_storage_client,
    provider_resolver_for,
)


@pytest.fixture(autouse=True)
def graph_override() -> Iterator[CompiledStateGraph[GraphState]]:
    """Every test in this file gets a fresh in-memory-checkpointed graph
    via dependency override, instead of the real lifespan's
    Postgres-backed one (which only exists inside `db_client`'s
    `with TestClient(app) as client:` block -- most tests here use a
    plain `TestClient(app)` for the from-photo/resume endpoints, which
    skips lifespan entirely). Mirrors tests/test_graph.py's
    `compiled_graph` fixture; autouse because nearly every test in this
    file touches /from-photo or /resume, directly or via
    `_start_session` -- simpler than threading a fixture parameter
    through each one. Tests that need the actual graph object (to call
    a helper function directly, not through HTTP) request it by name.
    """
    graph: CompiledStateGraph[GraphState] = build_graph().compile(checkpointer=InMemorySaver())
    app.dependency_overrides[get_compiled_graph] = lambda: graph
    try:
        yield graph
    finally:
        app.dependency_overrides.pop(get_compiled_graph, None)


def test_health() -> None:
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_docs_urls_disabled_in_production() -> None:
    assert docs_urls("production") == (None, None, None)


def test_docs_urls_enabled_locally() -> None:
    docs_url, redoc_url, openapi_url = docs_urls("local")
    assert docs_url is not None
    assert redoc_url is not None
    assert openapi_url is not None


# --- POST /items/from-photo + resume ------------------------------------


def _parse_sse(body: str) -> list[tuple[str, dict[str, Any]]]:
    """Parse an SSE response body into (event, data) pairs, in order."""
    events: list[tuple[str, dict[str, Any]]] = []
    for block in body.strip("\n").split("\n\n"):
        if not block.strip():
            continue
        event_name: str | None = None
        data: dict[str, Any] | None = None
        for line in block.splitlines():
            if line.startswith("event: "):
                event_name = line.removeprefix("event: ")
            elif line.startswith("data: "):
                data = json.loads(line.removeprefix("data: "))
        assert event_name is not None, f"malformed SSE block (no event: line): {block!r}"
        assert data is not None, f"malformed SSE block (no data: line): {block!r}"
        events.append((event_name, data))
    return events


@pytest.fixture
def storage_override() -> Iterator[Any]:
    """The MockStorageClient in effect for the test; cleans up the
    FastAPI dependency override afterward so it doesn't leak into other
    tests in the same session.
    """
    mock = make_mock_storage_client()
    app.dependency_overrides[get_storage_client] = lambda: mock
    try:
        yield mock
    finally:
        app.dependency_overrides.pop(get_storage_client, None)


WINE_RETURNS: dict[str, Any] = {
    "category_router": CategoryRouterOutput(suggested_category="wine", confidence=0.9),
    "identify": IdentifyOutput(
        best_guess="Beringer Founders' Estate Cabernet Sauvignon 2019", confidence=0.88
    ),
    "ocr": OcrOutput(state="text_present", text="BERINGER 2019", reason=None),
    "generate_description_and_title": DescriptionOutput(
        title="Beringer Cabernet Sauvignon",
        description="A bottle of Beringer Cabernet Sauvignon, 2019.",
    ),
    "extract_structured": WineExtractionResult(
        fields=WineFields(producer="Beringer", varietal="Cabernet Sauvignon", vintage=2019),
        confidence_scores={"producer": 0.9, "varietal": 0.85, "vintage": 0.95},
    ),
}

OTHER_RETURNS: dict[str, Any] = {
    "category_router": CategoryRouterOutput(suggested_category="other", confidence=0.4),
    "identify": IdentifyOutput(best_guess="a stapler", confidence=0.7),
    "ocr": OcrOutput(state="no_text", text="", reason="no_text"),
    "generate_description_and_title": DescriptionOutput(
        title="Stapler", description="A standard office stapler."
    ),
}


def _start_session(
    client: TestClient,
    user_id: UUID,
    storage_override: Any,
    returns_by_node: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> str:
    """Run /from-photo to completion (paused at await_category) and
    return the thread_id, for resume tests to build on.
    """
    monkeypatch.setattr(registry, "provider_for", provider_resolver_for(returns_by_node))
    storage_path = f"photos/{user_id}/a.jpg"
    storage_override.downloads[storage_path] = b"fake-image-bytes"

    response = client.post(
        "/items/from-photo",
        json={"storage_path": storage_path},
        headers=bearer_header(user_id),
    )
    assert response.status_code == 200
    thread_id = _parse_sse(response.text)[0][1]["thread_id"]
    return str(thread_id)


def test_from_photo_happy_path_streams_through_await_category(
    monkeypatch: pytest.MonkeyPatch, storage_override: Any
) -> None:
    monkeypatch.setattr(registry, "provider_for", provider_resolver_for(WINE_RETURNS))
    user_id = uuid4()
    storage_path = f"photos/{user_id}/a.jpg"
    storage_override.downloads[storage_path] = b"fake-image-bytes"

    client = TestClient(app)
    response = client.post(
        "/items/from-photo",
        json={"storage_path": storage_path},
        headers=bearer_header(user_id),
    )

    assert response.status_code == 200
    events = _parse_sse(response.text)
    assert [name for name, _ in events] == ["session", "category_router", "await_category"]

    session_data = events[0][1]
    assert "thread_id" in session_data

    assert events[1][1] == {"suggested_category": "wine", "confidence": 0.9}

    await_data = events[2][1]
    assert await_data == {
        "thread_id": session_data["thread_id"],
        "suggested_category": "wine",
        "confidence": 0.9,
        "ttl_seconds": CHECKPOINT_TTL_SECONDS,
    }


def test_from_photo_rejects_mismatched_storage_path(storage_override: Any) -> None:
    user_id = uuid4()
    other_users_path = f"photos/{uuid4()}/a.jpg"

    client = TestClient(app)
    response = client.post(
        "/items/from-photo",
        json={"storage_path": other_users_path},
        headers=bearer_header(user_id),
    )

    assert response.status_code == 403
    # Never attempted a download -- SPEC.md Auth: "returns 403 without
    # loading the image or running the pipeline."
    assert storage_override.downloads == {}


def test_from_photo_returns_404_when_photo_missing(storage_override: Any) -> None:
    user_id = uuid4()
    client = TestClient(app)
    response = client.post(
        "/items/from-photo",
        json={"storage_path": f"photos/{user_id}/missing.jpg"},
        headers=bearer_header(user_id),
    )
    assert response.status_code == 404


def test_from_photo_requires_auth(storage_override: Any) -> None:
    client = TestClient(app)
    response = client.post("/items/from-photo", json={"storage_path": "photos/x/a.jpg"})
    assert response.status_code == 401


def test_resume_wine_happy_path_returns_complete_item_draft(
    monkeypatch: pytest.MonkeyPatch, storage_override: Any
) -> None:
    user_id = uuid4()
    client = TestClient(app)
    thread_id = _start_session(client, user_id, storage_override, WINE_RETURNS, monkeypatch)

    response = client.post(
        f"/items/from-photo/{thread_id}/resume",
        json={"category": "wine"},
        headers=bearer_header(user_id),
    )

    assert response.status_code == 200
    events = _parse_sse(response.text)
    names = [name for name, _ in events]
    # identify/ocr run in parallel -- order between the two isn't a
    # documented guarantee, so check them as a set; everything after is
    # strictly sequential.
    assert set(names[:2]) == {"identify", "ocr"}
    assert names[2:] == ["generate_description_and_title", "extract_structured", "complete"]

    data_by_event = dict(events)
    assert data_by_event["generate_description_and_title"] == {
        "title": "Beringer Cabernet Sauvignon",
        "description": "A bottle of Beringer Cabernet Sauvignon, 2019.",
    }
    assert data_by_event["extract_structured"]["fields"]["producer"] == "Beringer"

    complete = data_by_event["complete"]
    assert complete["category"] == "wine"
    assert complete["title"] == "Beringer Cabernet Sauvignon"
    assert complete["wine"]["producer"] == "Beringer"
    assert complete["wine"]["vintage"] == 2019
    assert complete["wine"]["user_id"] == str(user_id)
    assert complete["halloween"] is None
    assert complete["other"] is None


def test_resume_other_category_skips_extract_structured(
    monkeypatch: pytest.MonkeyPatch, storage_override: Any
) -> None:
    user_id = uuid4()
    client = TestClient(app)
    thread_id = _start_session(client, user_id, storage_override, OTHER_RETURNS, monkeypatch)

    def _resolve(node_name: str) -> Any:
        if node_name == "extract_structured":
            pytest.fail("extract_structured should be skipped entirely for category 'other'")
        return provider_resolver_for(OTHER_RETURNS)(node_name)

    monkeypatch.setattr(registry, "provider_for", _resolve)

    response = client.post(
        f"/items/from-photo/{thread_id}/resume",
        json={"category": "other"},
        headers=bearer_header(user_id),
    )

    assert response.status_code == 200
    events = _parse_sse(response.text)
    assert "extract_structured" not in [name for name, _ in events]

    complete = dict(events)["complete"]
    assert complete["category"] == "other"
    assert complete["wine"] is None
    assert complete["halloween"] is None
    assert complete["other"]["title"] == "Stapler"


def test_resume_rejects_mismatched_user(
    monkeypatch: pytest.MonkeyPatch, storage_override: Any
) -> None:
    owner_id = uuid4()
    other_user_id = uuid4()
    client = TestClient(app)
    thread_id = _start_session(client, owner_id, storage_override, WINE_RETURNS, monkeypatch)

    response = client.post(
        f"/items/from-photo/{thread_id}/resume",
        json={"category": "wine"},
        headers=bearer_header(other_user_id),
    )

    assert response.status_code == 403


def test_resume_nonexistent_thread_returns_403() -> None:
    client = TestClient(app)
    response = client.post(
        f"/items/from-photo/{uuid4()}/resume",
        json={"category": "wine"},
        headers=bearer_header(uuid4()),
    )
    assert response.status_code == 403


def test_resume_already_resumed_returns_409(
    monkeypatch: pytest.MonkeyPatch, storage_override: Any
) -> None:
    user_id = uuid4()
    client = TestClient(app)
    thread_id = _start_session(client, user_id, storage_override, WINE_RETURNS, monkeypatch)

    first = client.post(
        f"/items/from-photo/{thread_id}/resume",
        json={"category": "wine"},
        headers=bearer_header(user_id),
    )
    assert first.status_code == 200

    second = client.post(
        f"/items/from-photo/{thread_id}/resume",
        json={"category": "wine"},
        headers=bearer_header(user_id),
    )
    assert second.status_code == 409


async def test_load_snapshot_for_resume_expired_checkpoint_raises_410(
    monkeypatch: pytest.MonkeyPatch,
    storage_override: Any,
    graph_override: CompiledStateGraph[GraphState],
) -> None:
    # The HTTP layer never lets a client control the server's clock, so
    # this exercises the time-dependent 410 path by calling the helper
    # directly with a `now` far enough past the checkpoint's real
    # created_at to be expired -- a "time-advancing fixture" in spirit.
    # Reuses graph_override's own graph object (not a second one) so it
    # sees the same checkpoint _start_session created via HTTP.
    user_id = uuid4()
    client = TestClient(app)
    thread_id = _start_session(client, user_id, storage_override, WINE_RETURNS, monkeypatch)

    far_future = datetime.now(UTC) + timedelta(seconds=CHECKPOINT_TTL_SECONDS + 1)

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        await _load_snapshot_for_resume(graph_override, thread_id, user_id, now=far_future)
    assert exc_info.value.status_code == 410


# --- POST /items, GET /items, GET /items/{id} ---------------------------


@pytest.fixture
def db_client(postgres_url: str) -> Iterator[TestClient]:
    """A TestClient whose app lifespan creates a real DB pool against
    the testcontainers instance from conftest.py's postgres_url.

    Deliberately *not* `app.dependency_overrides[get_db_pool] = ...`
    with a pool built by a separate async fixture: asyncpg connections
    aren't safe to use across event loops, and a pool created by a
    pytest-asyncio fixture lives in a different loop than the one
    TestClient's request handling runs in -- that combination produces
    "cannot perform operation: another operation is in progress" from
    asyncpg. Routing DATABASE_URL_RUNTIME/DATABASE_URL_MIGRATIONS
    through the real lifespan means the pool is created *inside*
    TestClient's own loop instead.
    """
    with database_urls_pointed_at(postgres_url), TestClient(app) as client:
        yield client


def _wine_payload(user_id: UUID, **overrides: Any) -> dict[str, Any]:
    """A full WineItem-shaped request body for `user_id`. `id`/`user_id`
    in the payload itself are deliberately "poisoned" with random
    values distinct from the real ones, to prove POST /items ignores
    them (SPEC.md: "Server assigns id and user_id; client-provided
    values are ignored."). `photo_url` defaults to a path that *does*
    belong to `user_id` -- create_item's ownership check (PR #20's
    review) rejects anything else; pass photo_url= explicitly to test
    that check itself.
    """
    payload: dict[str, Any] = {
        "id": str(uuid4()),
        "user_id": str(uuid4()),
        "category": "wine",
        "photo_url": f"photos/{user_id}/a.jpg",
        "title": "Beringer Cabernet",
        "description": "A bottle of wine.",
        "notes": None,
        "estimated_value": None,
        "confidence_scores": {"producer": 0.9},
        "created_at": "2020-01-01T00:00:00Z",
        "updated_at": "2020-01-01T00:00:00Z",
        "producer": "Beringer",
        "varietal": "Cabernet Sauvignon",
        "vintage": 2019,
        "region": None,
        "country": None,
        "bottle_size": None,
    }
    payload.update(overrides)
    return payload


def _other_payload(user_id: UUID, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": str(uuid4()),
        "user_id": str(uuid4()),
        "category": "other",
        "photo_url": f"photos/{user_id}/b.jpg",
        "title": "Stapler",
        "description": "A standard office stapler.",
        "notes": None,
        "estimated_value": None,
        "confidence_scores": {},
        "created_at": "2020-01-01T00:00:00Z",
        "updated_at": "2020-01-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def test_create_item_ignores_client_provided_id_and_user_id(db_client: TestClient) -> None:
    user_id = uuid4()
    payload = _wine_payload(user_id)

    response = db_client.post("/items", json=payload, headers=bearer_header(user_id))

    assert response.status_code == 201
    body = response.json()
    assert body["id"] != payload["id"]
    assert body["user_id"] == str(user_id)
    assert body["user_id"] != payload["user_id"]
    assert body["category"] == "wine"
    assert body["producer"] == "Beringer"
    assert body["vintage"] == 2019


def test_create_item_requires_auth() -> None:
    # Fails at auth before touching the DB -- no db_client needed.
    client = TestClient(app)
    response = client.post("/items", json=_wine_payload(uuid4()))
    assert response.status_code == 401


def test_create_item_rejects_mismatched_photo_url(db_client: TestClient) -> None:
    # Regression test for PR #20's review: photo_url is free text on
    # the request body, distinct from POST /items/from-photo's
    # storage_path, but needs the same photos/<user_id>/ ownership
    # check -- otherwise a client could save another user's photo path
    # and later have a signed read URL generated for it.
    user_id = uuid4()
    other_users_photo = f"photos/{uuid4()}/a.jpg"

    response = db_client.post(
        "/items",
        json=_wine_payload(user_id, photo_url=other_users_photo),
        headers=bearer_header(user_id),
    )

    assert response.status_code == 403


def test_list_items_returns_only_own_items_newest_first(db_client: TestClient) -> None:
    user_a = uuid4()
    user_b = uuid4()

    db_client.post(
        "/items", json=_wine_payload(user_a, title="First"), headers=bearer_header(user_a)
    )
    db_client.post(
        "/items", json=_other_payload(user_a, title="Second"), headers=bearer_header(user_a)
    )
    db_client.post(
        "/items", json=_wine_payload(user_b, title="Not A's"), headers=bearer_header(user_b)
    )

    response = db_client.get("/items", headers=bearer_header(user_a))

    assert response.status_code == 200
    items = response.json()
    assert len(items) == 2
    assert [item["title"] for item in items] == ["Second", "First"]  # newest first
    assert all(item["user_id"] == str(user_a) for item in items)


def test_list_items_requires_auth() -> None:
    client = TestClient(app)
    response = client.get("/items")
    assert response.status_code == 401


def test_get_item_returns_own_item(db_client: TestClient) -> None:
    user_id = uuid4()
    created = db_client.post(
        "/items", json=_wine_payload(user_id), headers=bearer_header(user_id)
    ).json()

    response = db_client.get(f"/items/{created['id']}", headers=bearer_header(user_id))

    assert response.status_code == 200
    assert response.json()["id"] == created["id"]
    assert response.json()["producer"] == "Beringer"


def test_get_item_404_for_nonexistent(db_client: TestClient) -> None:
    response = db_client.get(f"/items/{uuid4()}", headers=bearer_header(uuid4()))
    assert response.status_code == 404


def test_get_item_404_for_other_users_item(db_client: TestClient) -> None:
    owner = uuid4()
    other_user = uuid4()
    created = db_client.post(
        "/items", json=_wine_payload(owner), headers=bearer_header(owner)
    ).json()

    response = db_client.get(f"/items/{created['id']}", headers=bearer_header(other_user))

    assert response.status_code == 404


# --- PATCH /items/{id}, DELETE /items/{id} -------------------------------


def test_update_item_mutable_field_succeeds(db_client: TestClient) -> None:
    user_id = uuid4()
    created = db_client.post(
        "/items", json=_wine_payload(user_id), headers=bearer_header(user_id)
    ).json()

    response = db_client.patch(
        f"/items/{created['id']}",
        json={"estimated_value": "45.00"},
        headers=bearer_header(user_id),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["estimated_value"] == "45.00"
    assert body["title"] == created["title"]  # untouched
    assert body["updated_at"] != created["updated_at"]  # refreshed server-side


def test_update_item_category_specific_field_succeeds(db_client: TestClient) -> None:
    user_id = uuid4()
    created = db_client.post(
        "/items", json=_wine_payload(user_id), headers=bearer_header(user_id)
    ).json()

    response = db_client.patch(
        f"/items/{created['id']}", json={"vintage": 2020}, headers=bearer_header(user_id)
    )

    assert response.status_code == 200
    assert response.json()["vintage"] == 2020


def test_update_item_category_specific_field_preserves_other_details(
    db_client: TestClient,
) -> None:
    # Regression test for PR #21's review: an earlier revision rewrote
    # the entire `details` JSONB column from a pre-fetched snapshot on
    # every PATCH (a lost-update race between concurrent patches to
    # different fields). The fix merges only the patched keys via
    # Postgres's || operator -- this pins down that the merge actually
    # preserves sibling category-specific fields rather than wiping
    # them back to whatever was read before this specific request.
    user_id = uuid4()
    created = db_client.post(
        "/items", json=_wine_payload(user_id), headers=bearer_header(user_id)
    ).json()
    assert created["producer"] == "Beringer"

    response = db_client.patch(
        f"/items/{created['id']}", json={"vintage": 2020}, headers=bearer_header(user_id)
    )

    assert response.status_code == 200
    body = response.json()
    assert body["vintage"] == 2020
    assert body["producer"] == "Beringer"  # untouched by the patch
    assert body["varietal"] == "Cabernet Sauvignon"  # untouched by the patch


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("id", str(uuid4())),
        ("user_id", str(uuid4())),
        ("category", "other"),
        ("photo_url", "photos/someone-else/a.jpg"),
        ("created_at", "2020-01-01T00:00:00Z"),
        ("confidence_scores", {"producer": 1.0}),
    ],
)
def test_update_item_rejects_immutable_fields(
    db_client: TestClient, field: str, value: Any
) -> None:
    user_id = uuid4()
    created = db_client.post(
        "/items", json=_wine_payload(user_id), headers=bearer_header(user_id)
    ).json()

    response = db_client.patch(
        f"/items/{created['id']}", json={field: value}, headers=bearer_header(user_id)
    )

    assert response.status_code == 400


def test_update_item_404_for_nonexistent(db_client: TestClient) -> None:
    response = db_client.patch(
        f"/items/{uuid4()}", json={"title": "New Title"}, headers=bearer_header(uuid4())
    )
    assert response.status_code == 404


def test_update_item_404_for_other_users_item(db_client: TestClient) -> None:
    owner = uuid4()
    other_user = uuid4()
    created = db_client.post(
        "/items", json=_wine_payload(owner), headers=bearer_header(owner)
    ).json()

    response = db_client.patch(
        f"/items/{created['id']}",
        json={"title": "New Title"},
        headers=bearer_header(other_user),
    )

    assert response.status_code == 404


def test_update_item_requires_auth() -> None:
    client = TestClient(app)
    response = client.patch(f"/items/{uuid4()}", json={"title": "New Title"})
    assert response.status_code == 401


def test_delete_item_removes_it_and_deletes_photo(
    db_client: TestClient, storage_override: Any
) -> None:
    user_id = uuid4()
    created = db_client.post(
        "/items", json=_wine_payload(user_id), headers=bearer_header(user_id)
    ).json()

    response = db_client.delete(f"/items/{created['id']}", headers=bearer_header(user_id))

    assert response.status_code == 204
    assert storage_override.deleted_paths == [created["photo_url"]]

    listing = db_client.get("/items", headers=bearer_header(user_id))
    assert listing.json() == []


def test_delete_item_succeeds_even_if_storage_delete_fails(
    db_client: TestClient, storage_override: Any
) -> None:
    # Best-effort storage cleanup (see delete_item's docstring): the DB
    # row is the source of truth for GET /items, so a storage-side
    # failure must not turn a successful delete into an error response.
    user_id = uuid4()
    created = db_client.post(
        "/items", json=_wine_payload(user_id), headers=bearer_header(user_id)
    ).json()

    async def _raise(path: str) -> None:
        raise RuntimeError("simulated storage outage")

    storage_override.delete = _raise

    response = db_client.delete(f"/items/{created['id']}", headers=bearer_header(user_id))

    assert response.status_code == 204
    listing = db_client.get("/items", headers=bearer_header(user_id))
    assert listing.json() == []


def test_delete_item_404_for_nonexistent(db_client: TestClient) -> None:
    response = db_client.delete(f"/items/{uuid4()}", headers=bearer_header(uuid4()))
    assert response.status_code == 404


def test_delete_item_404_for_other_users_item(db_client: TestClient) -> None:
    owner = uuid4()
    other_user = uuid4()
    created = db_client.post(
        "/items", json=_wine_payload(owner), headers=bearer_header(owner)
    ).json()

    response = db_client.delete(f"/items/{created['id']}", headers=bearer_header(other_user))

    assert response.status_code == 404


def test_delete_item_requires_auth() -> None:
    client = TestClient(app)
    response = client.delete(f"/items/{uuid4()}")
    assert response.status_code == 401
