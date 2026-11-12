"""Smoke tests: the page and config load, validation and the desktop-only guard work.

They make no Kroger API calls. Run from backend/: python -m pytest
"""
from fastapi.testclient import TestClient

from kroger_lookup import main
from kroger_lookup.main import app

client = TestClient(app)


def test_index_page():
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    # Revalidated on every load, so an update never shows a cached older page
    assert response.headers["cache-control"] == "no-cache"


def test_static_file():
    assert client.get("/static/index.html").status_code == 200


def test_config():
    response = client.get("/api/config")
    assert response.status_code == 200
    assert response.json()["webMode"] is main.WEB_MODE


def test_query_validation_rejects_large_limit():
    # limit is capped at 50; validation fails before any Kroger call
    assert client.get("/api/products?limit=999").status_code == 422


def test_desktop_only_rejects_other_hosts():
    # TestClient sends Host: testserver, which desktop_only() must refuse (404 in web mode)
    response = client.post("/api/setup", json={})
    assert response.status_code == (404 if main.WEB_MODE else 403)


def test_desktop_only_requires_json():
    response = client.post(
        "/api/setup", content="{}", headers={"host": "127.0.0.1", "content-type": "text/plain"}
    )
    assert response.status_code == (404 if main.WEB_MODE else 415)
