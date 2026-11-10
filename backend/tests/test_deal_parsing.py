"""Deal parsing against one real atlas response pair (see tests/fixtures/atlas_capture.json).

The fixtures are unmodified kroger.com responses for store 01400929, captured 2026-11-10.
They cover a Yellow Tag promo, a Price Drop promo, a MEGA_EVENT offer, Buy N Get N offers,
an N-for-$X multi-buy, a digital coupon, an out-of-stock item, and an item with no deal.
"""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from kroger_lookup import main
from kroger_lookup.main import _parse_atlas_response, _parse_product_promos, app

FIXTURES = Path(__file__).parent / "fixtures"
CAPTURE = json.loads((FIXTURES / "atlas_capture.json").read_text(encoding="utf-8"))
PRODUCT_TEXT = (FIXTURES / "atlas_product.json").read_text(encoding="utf-8")
COUPONS_TEXT = (FIXTURES / "atlas_coupons.json").read_text(encoding="utf-8")
UPCS = CAPTURE["upcs"]

YELLOW_TAG = "0001600012685"   # $7.49 -> $6.99, plus the digital coupon
PRICE_DROP = "0088491212971"   # $3.99 -> $3.79, plus a MEGA_EVENT offer
BUY3_GET3 = "0004900002892"    # MUST_BUY "Buy 3 Get 3 Free"
BUY2_GET1 = "0007800008216"    # MUST_BUY "Buy 2 Get 1 Free."
FOUR_FOR_10 = "0002840080979"  # MUST_BUY "4/$10"
OUT_OF_STOCK = "0004900056132"
NO_DEAL = "0003000057322"


@pytest.fixture(scope="module")
def product():
    return _parse_product_promos(json.loads(PRODUCT_TEXT), UPCS)


@pytest.fixture(scope="module")
def coupons():
    return _parse_atlas_response(json.loads(COUPONS_TEXT), UPCS)


def by_source(deals, source):
    return [d for d in deals if d["source"] == source]


# ── product response: promos and offers ──

def test_every_upc_is_matched_and_priced(product):
    deals, pricing = product
    assert set(deals) == set(UPCS)
    assert set(pricing) == set(UPCS)


def test_yellow_tag_promo(product):
    deals, pricing = product
    (promo,) = by_source(deals[YELLOW_TAG], "promo")
    assert promo["badge"] == "YellowTag"
    assert promo["text"] == "$6.99"
    assert promo["value"] == "USD 6.99"  # atlas nforPrice string; the frontend reads the digits
    assert pricing[YELLOW_TAG]["reg"] == 7.49
    assert pricing[YELLOW_TAG]["promo"] == 6.99


def test_price_drop_promo_and_mega_event_offer(product):
    deals, pricing = product
    (promo,) = by_source(deals[PRICE_DROP], "promo")
    assert promo["badge"] == "PriceDrop"
    assert promo["value"] == "USD 3.79"
    assert pricing[PRICE_DROP] == {"reg": 3.99, "promo": 3.79, "outOfStock": False, "size": "11 oz"}
    (offer,) = by_source(deals[PRICE_DROP], "offer")
    assert offer["badge"] == "MEGA_EVENT"
    assert offer["text"] == "Save $2 each when you buy 3 or more"


@pytest.mark.parametrize("upc, text", [
    (BUY3_GET3, "Buy 3 Get 3 Free. Limit 12 Packages."),
    (BUY2_GET1, "Buy 2 Get 1 Free."),
])
def test_buy_n_get_n_offers(product, upc, text):
    deals, _ = product
    (offer,) = deals[upc]
    assert offer["source"] == "offer"
    assert offer["badge"] == "MUST_BUY"
    assert offer["text"] == text
    assert offer["nfor"] is None and offer["value"] is None


def test_n_for_x_multi_buy(product):
    deals, _ = product
    (offer,) = deals[FOUR_FOR_10]
    assert offer["badge"] == "MUST_BUY"
    assert offer["nfor"] == 4
    assert offer["value"] == 10.0


def test_out_of_stock_flag(product):
    _, pricing = product
    assert pricing[OUT_OF_STOCK]["outOfStock"] is True
    assert sum(p["outOfStock"] for p in pricing.values()) == 1


def test_item_without_deal_still_priced(product):
    deals, pricing = product
    assert deals[NO_DEAL] == []
    assert pricing[NO_DEAL]["reg"] == 3.99
    assert pricing[NO_DEAL]["promo"] is None


def test_product_matching_ignores_leading_zeros(product):
    stripped = [u.lstrip("0") for u in UPCS]
    deals, _ = _parse_product_promos(json.loads(PRODUCT_TEXT), stripped)
    assert deals[YELLOW_TAG.lstrip("0")]


# ── coupons response ──

def test_coupon_matches_its_upcs_only(coupons):
    with_coupon = {u for u, d in coupons.items() if d}
    assert YELLOW_TAG in with_coupon
    assert PRICE_DROP not in with_coupon
    (coupon,) = coupons[YELLOW_TAG]
    assert coupon["source"] == "coupon"
    assert coupon["badge"] == "Weekly Digital Deals"
    assert coupon["text"] == "$3.99 GM Giant Size Cereal"
    assert coupon["value"] == 3.99


def test_coupons_broadcast_when_none_match():
    # The API pre-filters by UPC; if no coupon lists a requested UPC, each applies to all of them.
    other = ["0000000000001", "0000000000002"]
    result = _parse_atlas_response(json.loads(COUPONS_TEXT), other)
    assert all(len(result[u]) == 1 for u in other)


def test_generic_coupon_types_get_no_badge():
    data = {"data": {"coupons": [{"upcs": ["0000000000001"], "type": "STANDARD",
                                  "displayType": "STANDARD", "displayDescription": "Save $1"}]}}
    (deal,) = _parse_atlas_response(data, ["0000000000001"])["0000000000001"]
    assert deal["badge"] is None


# ── /api/deals/parse end to end ──

desktop = pytest.mark.skipif(main.WEB_MODE, reason="deals endpoints are desktop-only")
LOCAL = {"host": "127.0.0.1"}


@desktop
def test_parse_endpoint_merges_product_and_coupon_deals():
    client = TestClient(app)
    body = {"upcs": UPCS, "responses": {
        "product": {"status": 200, "text": PRODUCT_TEXT},
        "coupons": {"status": 200, "text": COUPONS_TEXT},
    }}
    out = client.post("/api/deals/parse", json=body, headers=LOCAL).json()
    assert "_error" not in out
    assert {d["source"] for d in out[YELLOW_TAG]} == {"promo", "coupon"}
    assert out["_atlas_pricing"][OUT_OF_STOCK]["outOfStock"] is True


@desktop
def test_parse_endpoint_reports_product_403():
    client = TestClient(app)
    body = {"upcs": UPCS[:1], "responses": {"product": {"status": 403, "text": "Access Denied"}}}
    out = client.post("/api/deals/parse", json=body, headers=LOCAL).json()
    assert out["_error"] == "forbidden"


@desktop
def test_parse_endpoint_reports_total_failure():
    client = TestClient(app)
    body = {"upcs": UPCS[:1], "responses": {
        "product": {"error": "TypeError: Failed to fetch"},
        "coupons": {"status": 500, "text": ""},
    }}
    out = client.post("/api/deals/parse", json=body, headers=LOCAL).json()
    assert out["_error"] == "atlas_error"
