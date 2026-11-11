"""Helper functions: UPC padding, the image proxy allow-list, atlas headers and the deals plan."""
import json

import pytest
from fastapi.testclient import TestClient

from kroger_lookup import main
from kroger_lookup.main import _allowed_image_url, _atlas_headers, app, pad_upc


@pytest.mark.parametrize("raw, padded", [
    ("2840051777", "0002840051777"),
    ("0002840051777", "0002840051777"),
    (" 028-400-51777 ", "0002840051777"),
    ("4011", "0000000004011"),
])
def test_pad_upc(raw, padded):
    assert pad_upc(raw) == padded


@pytest.mark.parametrize("url", [
    "https://www.kroger.com/product/images/medium/front/0001600012685",
    "https://images.kroger.com/x.jpg",
    "https://www.kroger.com:443/x.jpg",
])
def test_image_proxy_allows_kroger_https(url):
    assert _allowed_image_url(url)


@pytest.mark.parametrize("url", [
    "http://www.kroger.com/x.jpg",                 # not https
    "https://evilkroger.com/x.jpg",                # suffix without a dot
    "https://kroger.com.evil.example/x.jpg",       # Kroger name as a subdomain
    "http://169.254.169.254/?kroger.com",          # metadata address with kroger in the query
    "https://www.kroger.com:8443/x.jpg",           # non-default port
    "not a url",
])
def test_image_proxy_rejects_other_urls(url):
    assert not _allowed_image_url(url)


STORE = {
    "locationId": "01400929",
    "name": "Kroger - University Plaza",
    "address": {"addressLine1": "1 W Corry St", "city": "Cincinnati", "state": "OH", "zipCode": "45219"},
    "geolocation": {"latitude": 39.13, "longitude": -84.49},
}


def test_atlas_headers_build_pickup_laf_from_store(monkeypatch):
    monkeypatch.setattr(main, "_atlas_laf", None)
    h = _atlas_headers("01400929", store_data=STORE)
    assert h["User-Time-Zone"] == "UTC"
    (laf,) = json.loads(h["x-laf-object"])
    assert laf["modality"]["type"] == "PICKUP"
    assert laf["modality"]["handoffLocation"]["storeId"] == "01400929"
    assert laf["modality"]["handoffAddress"]["address"]["postalCode"] == "45219"
    assert h["x-modality-type"] == "PICKUP"
    assert json.loads(h["x-modality"])["locationId"] == "01400929"
    assert h["X-Facility-Id"] == "01400929"


def test_atlas_headers_without_laf_or_store(monkeypatch):
    monkeypatch.setattr(main, "_atlas_laf", None)
    h = _atlas_headers("01400929")
    assert "x-laf-object" not in h
    assert json.loads(h["x-modality"]) == {"type": "PICKUP", "locationId": "01400929"}


@pytest.mark.skipif(main.WEB_MODE, reason="deals endpoints are desktop-only")
def test_deals_plan(monkeypatch):
    monkeypatch.setattr(main, "_atlas_laf", None)
    client = TestClient(app)
    upcs = ["2840051777"] + [str(n) for n in range(1, 60)]
    out = client.post("/api/deals/plan", json={"upcs": upcs, "location_id": "01400929", "store": STORE},
                      headers={"host": "127.0.0.1"}).json()
    assert len(out["upcs"]) == 50                      # capped at 50
    assert out["upcs"][0] == "0002840051777"
    kinds = {r["kind"]: r["path"] for r in out["requests"]}
    assert kinds["product"].startswith("/atlas/v1/product/v2/products?")
    assert kinds["coupons"].startswith("/atlas/v1/savings-coupons/v1/coupons?")
    assert "filter.gtin13s=0002840051777" in kinds["product"]
    # Only headers a page's fetch() may set are passed to the browser window.
    assert {k.lower() for k in out["headers"]} <= main._BROWSER_SETTABLE_HEADERS
