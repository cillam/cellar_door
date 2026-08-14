"""Route tests for backend/app/main.py."""

from fastapi.testclient import TestClient

from app.main import app, docs_urls


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
