"""Offline tests for the MCP server layer (no network)."""

from __future__ import annotations

import json
import pathlib

import pytest

from zameen_mcp import client as client_mod
from zameen_mcp import server
from zameen_mcp.models import Listing, SearchResult

FIXTURES = pathlib.Path(__file__).resolve().parent.parent / "fixtures"
SEARCH_HTML = FIXTURES / "search_islamabad.html"


def L(**kw) -> Listing:
    base = dict(listing_id="123456", title="t", url="https://x/z-123456-1-1.html")
    base.update(kw)
    return Listing(**base)


# ------------------------------------------------------------- post-filter --

def test_verified_only_keeps_badged():
    out = server._post_filter([L(verified=True), L()], verified_only=True)
    assert [l.listing_id for l in out] == ["123456"]
    assert out[0].verified is True


def test_agent_tier_is_case_insensitive():
    out = server._post_filter(
        [L(agent_tier="Titanium"), L(agent_tier="gold")], agent_tier="TITANIUM"
    )
    assert len(out) == 1 and out[0].agent_tier == "Titanium"


def test_exclude_promoted_drops_hot_cards():
    out = server._post_filter([L(promoted=True), L(promoted=False)],
                              exclude_promoted=True)
    assert all(not l.promoted for l in out)


def test_max_price_requires_parseable_price():
    out = server._post_filter(
        [L(price_pkr=150_000_000), L(price_pkr=None), L(price_pkr=999)],
        max_price_pkr=200_000_000,
    )
    assert [l.price_pkr for l in out] == [150_000_000, 999]


# ------------------------------------------------------------ page fetching --

def test_collect_pages_dedupes_and_stops(monkeypatch):
    if not SEARCH_HTML.exists():
        pytest.skip("fixtures/ are local-only (gitignored)")
    html = SEARCH_HTML.read_text(encoding="utf-8")
    urls = []

    def fake_fetch(url):
        urls.append(url)
        return html

    monkeypatch.setattr(client_mod, "build_search_url",
                        lambda **kw: f"https://www.zameen.com/fake/page/{kw['page']}")
    monkeypatch.setattr(client_mod, "fetch", fake_fetch)

    listings, total, pages = server._collect_pages(
        city_slug="Islamabad-3", type_path="Homes", purpose="sale", beds_min=3
    )
    ids = [l.listing_id for l in listings]
    assert len(ids) == len(set(ids)), "duplicates leaked through"
    assert pages >= 1 and pages <= server._MAX_PAGES
    assert total == 14663  # fixture h1: '14,663 Properties for Sale in Islamabad'
    assert len(listings) >= 10


# ------------------------------------------------------------------- tools --

def _call(fn, *a, **kw):
    return json.loads(fn(*a, **kw))


def test_search_properties_happy_path_with_badge_filters(monkeypatch):
    if not SEARCH_HTML.exists():
        pytest.skip("fixtures/ are local-only (gitignored)")
    html = SEARCH_HTML.read_text(encoding="utf-8")
    seen_urls = []
    monkeypatch.setattr(client_mod, "build_search_url",
                        lambda **kw: f"https://fake/{kw['page']}")
    monkeypatch.setattr(client_mod, "fetch",
                        lambda url: seen_urls.append(url) or html)

    data = _call(server.search_properties, city="islamabad", min_beds=3,
                 verified_only=True, agent_tier="titanium", limit=5)
    assert "error" not in data
    assert data["filters_applied"]["verified_only"] is True
    assert data["filters_applied"]["agent_tier"] == "titanium"
    assert data["returned"] <= 5
    for l in data["listings"]:
        assert l["verified"] is True
        assert l["agent_tier"].lower() == "titanium"
        assert l["purpose"] == "sale"
        assert l["property_type"] == "homes"


def test_search_properties_unknown_city_is_clean_error():
    data = _call(server.search_properties, city="atlantis")
    assert "error" in data and "supported_cities" in data


def test_search_properties_rejects_bad_purpose_type_sort():
    assert "error" in _call(server.search_properties, city="islamabad", purpose="swap")
    assert "error" in _call(server.search_properties, city="islamabad",
                            property_type="castles")
    assert "error" in _call(server.search_properties, city="islamabad", sort="random")


def test_get_listing_details_passthrough(monkeypatch):
    monkeypatch.setattr(client_mod, "get_listing",
                        lambda ref: {"listing_id": ref, "title": "T"})
    data = _call(server.get_listing_details, "54646556")
    assert data["listing_id"] == "54646556"


def test_get_listing_details_network_error_becomes_json(monkeypatch):
    def boom(ref):
        raise ConnectionError("offline")

    monkeypatch.setattr(client_mod, "get_listing", boom)
    data = _call(server.get_listing_details, "999")
    assert "error" in data and data["listing"] == "999"


def test_list_supported_cities_shape():
    data = _call(server.list_supported_cities)
    assert isinstance(data["cities"], dict) and data["cities"]
    assert "homes" in data["property_types"]


# ------------------------------------------------------------------ models --

def test_models_roundtrip():
    r = SearchResult(total_results=7, listings=[L()], page=2,
                     next_page_url="https://x/next")
    d = r.to_dict()
    assert d["total_results"] == 7 and d["page"] == 2
    assert d["listings"][0]["listing_id"] == "123456"
    assert len(Listing.__dataclass_fields__) == 18  # exact contract width
