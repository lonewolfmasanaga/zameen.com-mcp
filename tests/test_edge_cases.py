"""Offline edge-case tests for parsers + server hardening (CONTRACTS-PROD AGENT-CORE).

Everything here uses inline HTML strings and monkeypatched client functions:
no network, no fixtures/ required (the suite must pass on a fresh clone).
"""

from __future__ import annotations

import json

import pytest

from zameen_mcp import client as client_mod
from zameen_mcp import server
from zameen_mcp import session as session_mod
from zameen_mcp import watchlist as watchlist_mod
from zameen_mcp.models import SearchResult
from zameen_mcp.parsers import (
    _parse_area,
    _parse_price_pkr,
    parse_listing_detail,
    parse_search,
)

# --------------------------------------------------------------------------
# HTML builders (offline strings only)
# --------------------------------------------------------------------------


def card_html(listing_id: str, *, title: str = "Test House", **labels) -> str:
    """One minimal search-result card; label spans are optional on purpose."""
    parts = [
        f'<li><a href="/Property/test-listing-{listing_id}-1-1.html">',
        f"<h2>{title}</h2>",
    ]
    for label, value in labels.items():
        if value is not None:
            parts.append(f'<span aria-label="{label.title()}">{value}</span>')
    parts.append("</a></li>")
    return "".join(parts)


def page_html(*cards: str, h1: str | None = None, next_url: str | None = None) -> str:
    body = ""
    if h1 is not None:
        body += f"<h1>{h1}</h1>"
    body += "".join(cards)
    if next_url is not None:
        body += f'<a title="Next" href="{next_url}">Next</a>'
    return f"<html><body>{body}</body></html>"


EMPTY_RESULT = SearchResult(total_results=None, listings=[], page=1,
                            next_page_url=None)


def _call(fn, *a, **kw) -> dict:
    """Invoke an MCP tool and decode its JSON body."""
    return json.loads(fn(*a, **kw))


# --------------------------------------------------------------------------
# parsers: price / area garbage tables
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # malformed display prices must yield None, never raise
        ("PKR --", None),
        ("--", None),
        ("PKR", None),
        ("PKR .-", None),
        ("Call for price", None),
        ("N/A", None),
        ("...", None),
        (",,,", None),
        ("PKR 1.2.3 Crore", None),  # unparsable float part
        # sanity anchors (already covered in test_parsers.py; keep 2 here)
        ("PKR 68 Thousand", 68_000),
        ("PKR 4.15 Crore", 41_500_000),
    ],
)
def test_price_pkr_malformed_inputs_table(text, expected):
    assert _parse_price_pkr(text) == expected


@pytest.mark.parametrize("text", [None, 12345, [], b"PKR 5 Lakh", {}])
def test_price_pkr_non_string_input_is_none(text):
    assert _parse_price_pkr(text) is None


@pytest.mark.parametrize(
    "text",
    ["Marla", "Kanal", "Sq. Ft.", "sqft", "approx 5", "", "--", "5"],
)
def test_area_without_number_or_unit_is_none_pair(text):
    assert _parse_area(text) == (None, None)


@pytest.mark.parametrize("text", [None, 42, b"5 Marla", ["5 Marla"]])
def test_area_non_string_input_is_none_pair(text):
    assert _parse_area(text) == (None, None)


# --------------------------------------------------------------------------
# parsers: unusable html documents
# --------------------------------------------------------------------------


@pytest.mark.parametrize("html", [None, "", "   ", b"<html></html>", 7])
def test_parse_search_tolerates_unusable_html(html):
    assert parse_search(html) == EMPTY_RESULT


@pytest.mark.parametrize("html", [None, "", b"<html></html>"])
def test_parse_detail_tolerates_unusable_html(html):
    detail = parse_listing_detail(html)
    assert detail["listing_id"] == ""
    assert detail["title"] == "" and detail["price_pkr"] is None
    assert set(detail) == {
        "listing_id", "title", "url", "price_text", "price_pkr", "location",
        "beds", "baths", "area_text", "area_value", "area_unit", "verified",
        "agent_tier", "promoted", "added_text", "image_url",
    }


def test_detail_none_url_param_still_parses():
    url = ("https://www.zameen.com/Property/x-55544433-1-1.html")
    detail = parse_listing_detail("<html><body><h1>T</h1></body></html>", url=url)
    assert detail["listing_id"] == "55544433"


# --------------------------------------------------------------------------
# parsers: cards with missing / garbage fields
# --------------------------------------------------------------------------


def test_bare_card_missing_all_optional_fields_defaults_clean():
    result = parse_search(page_html(card_html("111222333")))
    assert result.total_results is None
    (l,) = result.listings
    assert l.listing_id == "111222333"
    assert l.title == "Test House"
    assert l.url.startswith("https://www.zameen.com/Property/")
    assert l.price_text == "" and l.price_pkr is None
    assert l.location == "" and l.beds is None and l.baths is None
    assert l.area_text is None and l.area_value is None and l.area_unit is None
    assert l.verified is False and l.promoted is False and l.agent_tier == ""


@pytest.mark.parametrize(
    ("labels", "check"),
    [
        ({"price": "--"}, lambda l: l.price_pkr is None),
        ({"currency": "PKR"}, lambda l: l.price_text == "PKR" or l.price_text == ""),
        ({"area": "Marla"},
         lambda l: (l.area_value, l.area_unit) == (None, None)),
        ({"beds": "Beds"}, lambda l: l.beds is None),
        ({"baths": "-"}, lambda l: l.baths is None),
    ],
)
def test_card_with_single_garbage_label_never_raises(labels, check):
    result = parse_search(page_html(card_html("222333444", **labels)))
    assert len(result.listings) == 1
    assert check(result.listings[0])


def test_garbage_total_results_h1_yields_none_not_crash():
    result = parse_search(page_html(h1=",,, Properties for Sale in Nowhere"))
    assert result.total_results is None
    assert result.listings == []


def test_comma_grouped_total_results_still_parses():
    result = parse_search(page_html(h1="12,000 Properties for Sale in Lahore"))
    assert result.total_results == 12_000


# --------------------------------------------------------------------------
# parsers: duplicate listing ids within one page
# --------------------------------------------------------------------------


def test_duplicate_ids_within_page_dedupe_first_card_wins():
    first = card_html("777888999", title="First")
    second = card_html("777888999", title="Second")
    unique = card_html("888999000", title="Unique")
    listings = parse_search(page_html(first, second, unique)).listings
    ids = [l.listing_id for l in listings]
    assert ids == ["777888999", "888999000"], "dup leaked into one-page parse"
    assert listings[0].title == "First"


# --------------------------------------------------------------------------
# server: limit clamping (1..50)
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, 10),
        ("abc", 10),
        (True, 10),   # bools are treated as unset, not 1/0
        (False, 10),
        (0, 1),
        (-99, 1),
        (1, 1),
        (3, 3),
        (50, 50),
        (51, 50),
        (10**9, 50),
        (12.9, 12),
    ],
)
def test_clamp_limit_table(raw, expected):
    assert server._clamp_limit(raw) == expected


def test_max_pages_contract_unchanged():
    assert server._MAX_PAGES == 3  # page safety pin: do not widen silently


_THREE_CARDS = (
    card_html("100000001"), card_html("100000002"), card_html("100000003")
)


@pytest.fixture()
def fake_three_card_search(monkeypatch):
    """Serve ONE offline page of three distinct cards to client.fetch."""
    monkeypatch.setattr(
        client_mod, "fetch",
        lambda url: page_html(*_THREE_CARDS, h1="3 Properties for Sale"),
    )


@pytest.mark.parametrize(
    ("limit_arg", "filters_limit", "max_returned"),
    [
        (0, 1, 1),
        (-5, 1, 1),
        (2, 2, 2),
        (9999, 50, 3),  # clamp to 50, but only 3 cards exist
    ],
)
def test_search_properties_limit_clamped_and_reported(
    monkeypatch, fake_three_card_search, limit_arg, filters_limit, max_returned
):
    data = _call(server.search_properties, city="islamabad", limit=limit_arg)
    assert "error" not in data
    assert data["filters_applied"]["limit"] == filters_limit
    assert data["returned"] <= max_returned
    assert len(data["listings"]) == data["returned"]
    ids = [l["listing_id"] for l in data["listings"]]
    assert len(ids) == len(set(ids))


# --------------------------------------------------------------------------
# server: cross-page dedupe + pagination cap (_collect_pages)
# --------------------------------------------------------------------------


def test_collect_pages_dedupes_duplicate_ids_across_pages(monkeypatch):
    pages = [
        page_html(card_html("200000001"), card_html("200000002"),
                  next_url="/Homes/Islamabad-3-2.html"),
        page_html(card_html("200000002"), card_html("200000003")),
    ]
    monkeypatch.setattr(client_mod, "build_search_url",
                        lambda **kw: f"https://fake/page/{kw['page']}")
    monkeypatch.setattr(client_mod, "fetch", lambda url: pages.pop(0))

    listings, total, pages_fetched = server._collect_pages(
        city_slug="Islamabad-3", type_path="Homes", purpose="sale",
    )
    assert [l.listing_id for l in listings] == ["200000001", "200000002",
                                                "200000003"]
    assert pages_fetched == 2


def test_collect_pages_cap_holds_against_endless_next_links(monkeypatch):
    counter = {"n": 0}

    def endless_fetch(url):
        counter["n"] += 1
        return page_html(card_html(f"30000{counter['n']:04d}"),
                         next_url=f"/Homes/Islamabad-3-{counter['n'] + 1}.html")

    monkeypatch.setattr(client_mod, "build_search_url",
                        lambda **kw: f"https://fake/page/{kw['page']}")
    monkeypatch.setattr(client_mod, "fetch", endless_fetch)

    listings, _total, pages_fetched = server._collect_pages(
        city_slug="Islamabad-3", type_path="Homes", purpose="sale",
    )
    assert pages_fetched == server._MAX_PAGES
    assert len(listings) == server._MAX_PAGES


# --------------------------------------------------------------------------
# server: every tool keeps the JSON error shape under failure
# --------------------------------------------------------------------------


def test_search_properties_network_error_is_json(monkeypatch,
                                                 fake_three_card_search):
    def boom(url):
        raise ConnectionError("offline")

    monkeypatch.setattr(client_mod, "fetch", boom)
    data = _call(server.search_properties, city="islamabad")
    assert data["error"].startswith("fetch failed:")
    assert data["city"] == "islamabad"  # filters are spread into error bodies


def test_draft_agent_message_empty_ref_is_json_error():
    data = _call(server.draft_agent_message, listing="   ")
    assert "error" in data


def test_draft_agent_message_fetch_failure_is_json(monkeypatch):
    def boom(ref):
        raise ConnectionError("offline")

    monkeypatch.setattr(client_mod, "get_listing", boom)
    data = _call(server.draft_agent_message, listing="123456")
    assert data["error"].startswith("fetch failed:")


def test_list_supported_cities_survives_broken_client_state(monkeypatch):
    monkeypatch.setattr(client_mod, "CITY_SLUGS", None)  # .items() would blow up
    data = _call(server.list_supported_cities)
    assert "error" in data


def test_account_status_survives_status_failure(monkeypatch):
    def boom(path=None):
        raise RuntimeError("corrupt store")

    monkeypatch.setattr(session_mod, "status", boom)
    data = _call(server.account_status)
    assert data["logged_in"] is False and "error" in data


def test_add_watch_seeding_failure_does_not_create_watch(tmp_path, monkeypatch):
    monkeypatch.setattr(watchlist_mod, "WATCHES_FILE", tmp_path / "w.json")
    monkeypatch.setattr(client_mod, "build_search_url",
                        lambda **kw: "https://fake/page/1")
    monkeypatch.setattr(
        client_mod, "fetch",
        lambda url: (_ for _ in ()).throw(ConnectionError("offline")),
    )
    data = _call(server.add_watch, "never-seeded", city="islamabad")
    assert data.get("watch_not_created") is True
    assert watchlist_mod.get("never-seeded", path=tmp_path / "w.json") is None


def test_check_watch_unknown_watch_reports_existing_names(tmp_path, monkeypatch):
    monkeypatch.setattr(watchlist_mod, "WATCHES_FILE", tmp_path / "w.json")
    watchlist_mod.add("real", {"city": "islamabad"}, path=tmp_path / "w.json")
    data = _call(server.check_watch, "ghost")
    assert "no watch named 'ghost'" in data["error"]
    assert "real" in data["existing_watches"]


def test_check_watch_corrupt_store_is_clean_json(tmp_path, monkeypatch):
    corrupt = tmp_path / "watches.json"
    corrupt.write_text("{not json at all", encoding="utf-8")
    monkeypatch.setattr(watchlist_mod, "WATCHES_FILE", corrupt)
    assert _call(server.check_watch, "any")["error"]
    assert _call(server.remove_watch, "any") == {"removed": False}
    assert _call(server.list_watches) == {"watches": {}}


# --------------------------------------------------------------------------
# server: check_watch limit clamp end-to-end (offline)
# --------------------------------------------------------------------------


def test_check_watch_limit_clamped_end_to_end(tmp_path, monkeypatch):
    store = tmp_path / "watches.json"
    monkeypatch.setattr(watchlist_mod, "WATCHES_FILE", store)
    watchlist_mod.add("w", {"city": "islamabad"}, seed_ids=[], path=store)
    monkeypatch.setattr(client_mod, "build_search_url",
                        lambda *a, **kw: "https://fake/page/1")
    monkeypatch.setattr(
        client_mod, "fetch", lambda url: page_html(*_THREE_CARDS)
    )

    clamped = _call(server.check_watch, "w", limit=0)
    assert clamped["new_since_last_check"] == 3
    assert len(clamped["listings"]) == 1  # clamp floor of 1 applied

    normal = _call(server.check_watch, "w", limit=2)
    assert normal["new_since_last_check"] == 0  # all three were recorded above
    assert normal["matching_now"] == 3

    watchlist_mod.record_check("w", [], path=store)  # reset seen ids
    wide = _call(server.check_watch, "w", limit=500)
    assert len(wide["listings"]) == 3  # clamp ceiling never exceeds stock
