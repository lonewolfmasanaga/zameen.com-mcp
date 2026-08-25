"""Offline tests for zameen_mcp.parsers + zameen_mcp.client.

Runs against real saved pages in fixtures/ (no network):
- fixtures/search_islamabad.html : Islamabad Homes-for-sale search,
  beds_in=3, sort=price_asc (live capture).
- fixtures/listing_sample.html   : one Property detail page (live capture).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from zameen_mcp.client import (
    CITY_SLUGS,
    TYPE_PATHS,
    build_search_url,
    search,
)
from zameen_mcp.models import Listing, SearchResult
from zameen_mcp.parsers import parse_listing_detail, parse_search

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"

SEARCH_HTML_PATH = FIXTURES / "search_islamabad.html"
LISTING_HTML_PATH = FIXTURES / "listing_sample.html"

DETAIL_KEYS = {
    "listing_id",
    "title",
    "url",
    "price_text",
    "price_pkr",
    "location",
    "beds",
    "baths",
    "area_text",
    "area_value",
    "area_unit",
    "verified",
    "agent_tier",
    "promoted",
    "added_text",
    "image_url",
}


@pytest.fixture(scope="module")
def search_html() -> str:
    if not SEARCH_HTML_PATH.exists():
        pytest.skip("fixtures/ are local-only (gitignored); capture pages first")
    return SEARCH_HTML_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def detail_html() -> str:
    if not LISTING_HTML_PATH.exists():
        pytest.skip("fixtures/ are local-only (gitignored); capture pages first")
    return LISTING_HTML_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def search_result(search_html: str) -> SearchResult:
    return parse_search(search_html)


# --------------------------------------------------------------------------
# parse_search
# --------------------------------------------------------------------------


def test_search_total_results(search_result: SearchResult) -> None:
    # h1 on the fixture page: "14,663 Properties for Sale in Islamabad"
    assert search_result.total_results == 14_663


def test_search_next_page_url(search_result: SearchResult) -> None:
    assert search_result.next_page_url == (
        "https://www.zameen.com/Homes/Islamabad-3-2.html"
    )


def test_search_listing_count_and_uniqueness(
    search_result: SearchResult,
) -> None:
    assert len(search_result.listings) == 25
    ids = [l.listing_id for l in search_result.listings]
    assert len(set(ids)) == 25
    assert search_result.page == 1  # parser default; client overrides


def test_search_first_listing_fields(search_result: SearchResult) -> None:
    first = search_result.listings[0]
    assert first.listing_id == "54284067"
    assert "DHA Phase 5" in first.title
    assert first.url == (
        "https://www.zameen.com/Property/"
        "dha_defence_dha_defence_phase_5_5_marla_house_for_sale_in_"
        "dha_phase_5_prime_location-54284067-10991-1.html"
    )
    assert first.price_text == "PKR 4.15 Crore"
    assert first.price_pkr == 41_500_000
    assert first.location == "DHA Defence Phase 5, DHA Defence"
    assert first.beds == 3
    assert first.baths == 4
    assert first.area_text == "5 Marla"
    assert first.area_value == 5.0
    assert first.area_unit == "Marla"
    assert first.verified is False  # this card carries no Verified badge
    assert first.agent_tier == "titanium"
    assert first.promoted is True  # "super hot" badge on this card
    assert first.added_text == "Added: 1 hour ago"
    assert first.image_url.startswith("https://media.zameen.com/")
    # parser never sets context fields; that is the client's job
    assert first.property_type == ""
    assert first.purpose == ""


def test_search_arab_price_and_updated_suffix(
    search_result: SearchResult,
) -> None:
    by_id = {l.listing_id: l for l in search_result.listings}
    arab = by_id["54495994"]
    assert arab.price_text == "PKR 2.1 Arab"
    assert arab.price_pkr == 2_100_000_000
    assert arab.added_text == "Added: 2 hours ago(Updated: 2 hours ago)"
    assert arab.area_unit == "Kanal"


def test_search_all_urls_absolute_property_links(
    search_result: SearchResult,
) -> None:
    for listing in search_result.listings:
        assert listing.url.startswith("https://www.zameen.com/Property/")
        assert listing.listing_id.isdigit() and len(listing.listing_id) >= 6


def test_search_verified_flag_only_on_badged_cards(
    search_result: SearchResult,
) -> None:
    # Exactly two cards in this fixture carry the literal "Verified" token.
    verified_ids = {
        l.listing_id for l in search_result.listings if l.verified
    }
    assert verified_ids == {"54562788", "54593794"}


def test_search_empty_html() -> None:
    result = parse_search("")
    assert result == SearchResult(
        total_results=None, listings=[], page=1, next_page_url=None
    )


def test_search_page_without_cards() -> None:
    result = parse_search(
        "<html><body><h1>0 Properties for Sale in Nowhere</h1></body></html>"
    )
    assert result.total_results == 0
    assert result.listings == []
    assert result.next_page_url is None


# --------------------------------------------------------------------------
# parse_listing_detail
# --------------------------------------------------------------------------


DETAIL_URL = (
    "https://www.zameen.com/Property/"
    "dha_defence_dha_defence_phase_5_5_marla_house_for_sale_in_"
    "dha_phase_5_prime_location-54284067-10991-1.html"
)


def test_detail_full_fields(detail_html: str) -> None:
    detail = parse_listing_detail(detail_html, url=DETAIL_URL)
    assert detail["listing_id"] == "54284067"
    assert detail["title"] == (
        "5 Marla House For Sale In DHA Phase 5 Prime Location"
    )
    assert detail["url"] == DETAIL_URL
    assert detail["price_text"] == "PKR 4.15 Crore"
    assert detail["price_pkr"] == 41_500_000
    assert "DHA Defence" in detail["location"]
    assert detail["beds"] == 3
    assert detail["baths"] == 4
    assert detail["area_text"] == "5 Marla"
    assert detail["area_value"] == 5.0
    assert detail["area_unit"] == "Marla"
    assert detail["verified"] is False  # no Verified badge on this page
    assert detail["agent_tier"] == "titanium"
    assert detail["promoted"] is False
    assert detail["added_text"] == "Added: 2 hours ago"
    assert detail["image_url"].startswith("https://media.zameen.com/")


def test_detail_keys_mirror_listing_contract(detail_html: str) -> None:
    detail = parse_listing_detail(detail_html, url=DETAIL_URL)
    assert set(detail) == DETAIL_KEYS
    assert "property_type" not in detail
    assert "purpose" not in detail


def test_detail_uses_canonical_link_when_url_missing(detail_html: str) -> None:
    detail = parse_listing_detail(detail_html, url="")
    assert detail["listing_id"] == "54284067"
    assert detail["url"] == DETAIL_URL


def test_detail_empty_html() -> None:
    detail = parse_listing_detail("", url="")
    assert set(detail) == DETAIL_KEYS
    assert detail["listing_id"] == ""
    assert detail["title"] == ""
    assert detail["price_pkr"] is None
    assert detail["beds"] is None
    assert detail["verified"] is False


# --------------------------------------------------------------------------
# price/area parsing rules (CONTRACTS.md)
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("PKR 68 Thousand", 68_000),
        ("PKR 50 Lakh", 5_000_000),
        ("PKR 4.15 Crore", 41_500_000),
        ("PKR 2.1 Arab", 2_100_000_000),
        ("PKR 25,000", 25_000),  # bare digits stay as-is, commas stripped
        ("1.3 Crore", 13_000_000),
        ("PKR Call for price", None),
        ("", None),
    ],
)
def test_price_pkr_rule(text: str, expected: int | None) -> None:
    detail = parse_listing_detail(
        f'<html><body><span aria-label="Currency">PKR</span>'
        f'<span aria-label="Price">{text}</span></body></html>'
    )
    assert detail["price_pkr"] == expected


def test_area_regex_variants() -> None:
    for text, value, unit in [
        ("5 Marla", 5.0, "Marla"),
        ("1.3 Kanal", 1.3, "Kanal"),
        ("150 Sq. Yd.", 150.0, "Sq. Yd."),
        ("1200 Sq. Ft.", 1200.0, "Sq. Ft."),
    ]:
        detail = parse_listing_detail(
            f'<html><body><span aria-label="Area">{text}</span></body></html>'
        )
        assert (detail["area_value"], detail["area_unit"]) == (value, unit), text


# --------------------------------------------------------------------------
# client: URL building + offline validation (no network)
# --------------------------------------------------------------------------


def test_build_search_url_minimal() -> None:
    assert (
        build_search_url("Islamabad-3", "Homes", "sale")
        == "https://www.zameen.com/Homes/Islamabad-3-1.html"
    )


def test_build_search_url_page_and_beds() -> None:
    assert build_search_url(
        "Islamabad-3", "Homes", "sale", page=2, beds_min=3
    ) == "https://www.zameen.com/Homes/Islamabad-3-2.html?beds_in=3"


def test_build_search_url_all_params_in_contract_order() -> None:
    url = build_search_url(
        "Karachi-2",
        "Flats_Apartments",
        "rent",
        page=3,
        beds_min=2,
        baths_min=1,
        price_min=15000,
        price_max=80000,
        area_min=3.0,
        area_max=5.0,
        keywords="sea view",
        sort="price_asc",
    )
    assert url == (
        "https://www.zameen.com/Flats_Apartments/Karachi-2-3.html"
        "?beds_in=2&baths_in=1&price_min=15000&price_max=80000"
        "&area_min=313.55&area_max=522.58&keywords=sea+view&sort=price_asc"
    )


def test_build_search_url_area_marla_to_sqm_conversion() -> None:
    # 1 Kanal of area_min (20 Marla) -> 2090.32 sqm
    url = build_search_url(
        "Lahore-1", "Plots", "sale", area_min=20.0
    )
    assert "area_min=2090.32" in url


def test_build_search_url_rejects_bad_input() -> None:
    with pytest.raises(ValueError):
        build_search_url("Islamabad-3", "Homes", "buy")
    with pytest.raises(ValueError):
        build_search_url("Islamabad-3", "Homes", "sale", sort="newest")
    with pytest.raises(ValueError):
        build_search_url("Islamabad-3", "Homes", "sale", page=0)


def test_type_paths_contract_keys() -> None:
    assert set(TYPE_PATHS) == {
        "homes",
        "houses",
        "flats",
        "plots",
        "commercial",
        "rooms",
    }
    assert TYPE_PATHS["homes"] == ("Homes", "Rentals")
    assert TYPE_PATHS["plots"] == ("Plots", "Rentals_Plots")


def test_city_slugs_confirmed_entries() -> None:
    assert CITY_SLUGS["islamabad"] == "Islamabad-3"
    assert CITY_SLUGS["hyderabad"] == "Hyderabad-30"  # live-verified
    for slug in CITY_SLUGS.values():
        assert re_fullmatch_slug(slug)


def re_fullmatch_slug(slug: str) -> bool:
    import re

    return re.fullmatch(r"[A-Za-z_]+-\d+", slug) is not None


def test_search_unknown_city_raises_before_network() -> None:
    with pytest.raises(ValueError, match="unsupported city"):
        search("atlantis")
    with pytest.raises(ValueError, match="unsupported property_type"):
        search("islamabad", property_type="castles")


def test_models_importable_and_defaults() -> None:
    listing = Listing(
        listing_id="1",
        title="t",
        url="u",
        price_text="PKR 1",
        price_pkr=1,
        location="l",
        beds=None,
        baths=None,
        area_text=None,
        area_value=None,
        area_unit=None,
    )
    assert listing.property_type == ""
    assert listing.verified is False


# --------------------------------------------------------------------------
# Rentals-page coverage (fixture captured 2026-08-22) + area normalization
# --------------------------------------------------------------------------

RENTALS_HTML_PATH = FIXTURES / "search_lahore_rentals.html"


@pytest.fixture(scope="module")
def rentals_result() -> SearchResult:
    if not RENTALS_HTML_PATH.exists():
        pytest.skip("fixtures/ are local-only (gitignored); capture pages first")
    return parse_search(RENTALS_HTML_PATH.read_text(encoding="utf-8"))


def test_rentals_total_results(rentals_result: SearchResult) -> None:
    # h1: "2,708 Flats for Rent in Lahore"
    assert rentals_result.total_results == 2_708


def test_rentals_sqft_areas_are_parsed_and_canonical(
    rentals_result: SearchResult,
) -> None:
    with_area = [
        l for l in rentals_result.listings
        if l.area_unit == "Sq. Ft." and l.area_value
    ]
    assert with_area, "no listing parsed a sqft area"


@pytest.mark.parametrize(
    ("raw", "value", "unit"),
    [
        ("450 sqft", 450.0, "Sq. Ft."),
        ("1,350 sqft", 1350.0, "Sq. Ft."),
        ("900 Sq. Ft.", 900.0, "Sq. Ft."),
        ("135 sq yd", 135.0, "Sq. Yd."),
        ("5 Marla", 5.0, "Marla"),
        ("1.3 Kanal", 1.3, "Kanal"),
    ],
)
def test_parse_area_variants(raw, value, unit):
    from zameen_mcp.parsers import _parse_area

    assert _parse_area(raw) == (value, unit)
