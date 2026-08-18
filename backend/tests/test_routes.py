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

from app.graph.schemas import (
    CategoryRouterOutput,
    DescriptionOutput,
    IdentifyOutput,
    OcrOutput,
    WineExtractionResult,
    WineFields,
)
from app.main import app, docs_urls
from app.providers import registry
from app.routers.items import CHECKPOINT_TTL_SECONDS, _load_snapshot_for_resume
from app.storage import get_storage_client
from tests.conftest import bearer_header, make_mock_storage_client, provider_resolver_for


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
    monkeypatch: pytest.MonkeyPatch, storage_override: Any
) -> None:
    # The HTTP layer never lets a client control the server's clock, so
    # this exercises the time-dependent 410 path by calling the helper
    # directly with a `now` far enough past the checkpoint's real
    # created_at to be expired -- a "time-advancing fixture" in spirit.
    user_id = uuid4()
    client = TestClient(app)
    thread_id = _start_session(client, user_id, storage_override, WINE_RETURNS, monkeypatch)

    far_future = datetime.now(UTC) + timedelta(seconds=CHECKPOINT_TTL_SECONDS + 1)

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        await _load_snapshot_for_resume(thread_id, user_id, now=far_future)
    assert exc_info.value.status_code == 410
