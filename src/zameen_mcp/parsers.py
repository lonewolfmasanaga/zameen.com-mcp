"""Parsers for Zameen.com search-result and property-detail HTML pages.

Deterministic, offline-capable extraction built on BeautifulSoup (lxml).
All public functions are pure: html in -> data out. No network access here.

Parsing anchors (ground truth from live Zameen.com markup):
- Search cards are ``<li>`` elements containing an ``<a>`` whose href matches
  ``/Property/...-<id>-<n>-<n>.html``; only outermost matching ``<li>`` nodes
  count as cards.
- Cards carry semantic ``aria-label`` hooks (Title, Currency, Price, Location,
  Beds, Baths, Area, Listing creation date, ...) with regex/text fallbacks.
- Badge tokens appear verbatim in card DOM: ``Verified``, ``Titanium``,
  ``super hot``, ``hot``. Matching is token-wise to avoid substring
  collisions (e.g. "photo" contains "hot").
"""

from __future__ import annotations

import logging
import re
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .models import Listing, SearchResult

logger = logging.getLogger(__name__)

__all__ = ["parse_search", "parse_listing_detail"]

_BASE_URL = "https://www.zameen.com"

# /Property/<slug>-<listing_id>-<type_id>-<n>.html ; capture group 1 = id
_PROPERTY_HREF_RE = re.compile(
    r"(?:https://www\.zameen\.com)?(/Property/.+?-(\d{6,})-\d+-\d+\.html)"
)

_AREA_RE = re.compile(
    r"([\d.,]+)\s*(Marla|Kanal|Sq\.?\s?Yd(?:s|ds)?\.?|Sq\.?\s?Ft(?:\.|t)?|sqft|sq\s?yd)",
    re.IGNORECASE,
)

_TOTAL_RE = re.compile(
    r"([\d,]+)\s+(?:Properties?|Flats?|Houses?|Plots?|Rooms?|Shops?"
    r"|Offices?|Apartments?|Homes?)\b",
    re.IGNORECASE,
)

# Price words -> PKR multiplier (CONTRACTS.md PKR parsing rule)
_PRICE_MULTIPLIERS = {
    "thousand": 1_000,
    "lakh": 100_000,
    "crore": 10_000_000,
    "arab": 1_000_000_000,
}

_PRICE_RE = re.compile(r"([\d.,]+)\s*(thousand|lakh|crore|arab)?", re.IGNORECASE)

# Word-boundary badge tokens (case-sensitive per live markup)
_VERIFIED_TOKEN_RE = re.compile(r"\bVerified\b")
_PROMO_TOKEN_RE = re.compile(r"\bsuper hot\b|\bhot\b")

_AGENT_TIERS = ("titanium", "platinum", "gold", "silver", "bronze")

_LISTING_FIELDS = (
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
)


def _soup(html: str) -> BeautifulSoup:
    """Parse *html* with lxml, degrading gracefully on empty input."""
    return BeautifulSoup(html or "", "lxml")


def _parse_price_pkr(price_text: str) -> Optional[int]:
    """Convert a display price such as ``"PKR 4.15 Crore"`` to integer PKR.

    Multipliers: Thousand x1_000, Lakh x100_000, Crore x10_000_000,
    Arab x1_000_000_000; bare digits stay as-is; commas stripped.
    Returns None when no numeric part is found.

    >>> _parse_price_pkr("PKR 68 Thousand")
    68000
    """
    if not price_text:
        return None
    match = _PRICE_RE.search(price_text.replace(",", ""))
    if not match:
        return None
    try:
        value = float(match.group(1))
    except ValueError:
        return None
    multiplier = _PRICE_MULTIPLIERS.get((match.group(2) or "").lower(), 1)
    return int(value * multiplier)


def _parse_area(area_text: str) -> tuple[Optional[float], Optional[str]]:
    """Split an area string like ``"5 Marla"`` into ``(value, unit)``.

    >>> _parse_area("1.3 Kanal")
    (1.3, 'Kanal')
    """
    if not area_text:
        return None, None
    match = _AREA_RE.search(area_text)
    if not match:
        return None, None
    raw = match.group(1).replace(",", "")
    try:
        value = float(raw)
    except ValueError:
        return None, None
    unit = re.sub(r"\s+", " ", match.group(2)).strip()
    # Canonicalize display variants: 'sqft', 'Sq.Ft', 'SQ FT' -> 'Sq. Ft.'
    lowered = unit.lower().replace(" ", "").replace(".", "")
    if lowered.startswith("sqyd"):
        unit = "Sq. Yd."
    elif lowered.startswith("sqft"):
        unit = "Sq. Ft."
    elif lowered in ("marla", "kanal"):
        unit = unit.title()
    return value, unit


def _int_prefix(text: str) -> Optional[int]:
    """Return the leading integer in *text* (e.g. ``"3 Beds" -> 3``)."""
    match = re.search(r"\d+", text or "")
    return int(match.group(0)) if match else None


def _find_label(soup_or_node, label: str):
    """First element whose ``aria-label`` equals *label* (case-insensitive)."""
    target = label.strip().lower()
    return soup_or_node.find(
        attrs={"aria-label": lambda v: v and v.strip().lower() == target}
    )


def _label_text(node, label: str) -> str:
    """Visible text of the element labelled *label*, or ``""``."""
    el = _find_label(node, label)
    return el.get_text(" ", strip=True) if el is not None else ""


def _img_src(img) -> str:
    """Best available URL from an <img>: src, then lazy data-src."""
    if img is None:
        return ""
    return (img.get("src") or "").strip() or (img.get("data-src") or "").strip()


def _badge_tier(scope) -> str:
    """Lowercased agent tier from a ``* badge`` aria-label span, e.g. 'titanium'.

    Ignores the generic Trusted/Verified badges. Falls back to a word-boundary
    scan for known tier names.
    """
    for el in scope.find_all(attrs={"aria-label": True}):
        label = el["aria-label"].strip()
        lowered = label.lower()
        if lowered.endswith("badge") and not lowered.startswith(
            ("trusted", "verified")
        ):
            tier = el.get_text(strip=True).lower()
            if tier:
                return tier
    page_text = scope.get_text(" ", strip=True)
    for tier in _AGENT_TIERS:
        if re.search(rf"\b{tier.capitalize()}\b", page_text):
            return tier
    return ""


def _is_promoted(node) -> bool:
    """True when a super hot/hot promo label or exact token is present."""
    for el in node.find_all(attrs={"aria-label": True}):
        if el["aria-label"].strip().lower() in ("super hot label", "hot label"):
            return True
    for el in node.find_all(string=_PROMO_TOKEN_RE):
        if str(el).strip() in ("super hot", "hot"):
            return True
    # Last resort: token-wise scan of the card's own text (never bare substring).
    return bool(_PROMO_TOKEN_RE.search(node.get_text(" ", strip=True)))


def _card_nodes(soup: BeautifulSoup) -> list:
    """Outermost <li> nodes that contain a Property anchor (search cards).

    Inner nested <li>s (share menus etc.) are skipped by requiring no matching
    <li> ancestor; duplicates by listing id are dropped preserving order.
    """
    matches = [
        li
        for li in soup.find_all("li")
        if li.find("a", href=_PROPERTY_HREF_RE)
    ]
    match_ids = {id(li) for li in matches}
    cards: list = []
    seen_ids: set[str] = set()
    for li in matches:
        # Skip <li>s nested inside another matching <li> (share menus etc.)
        if any(id(parent) in match_ids for parent in li.parents):
            continue
        href = li.find("a", href=_PROPERTY_HREF_RE)["href"]
        m = _PROPERTY_HREF_RE.search(href)
        listing_id = m.group(2)
        if listing_id in seen_ids:
            continue
        seen_ids.add(listing_id)
        cards.append(li)
    return cards


def _absolute_property_url(href: str) -> str:
    """Normalise a (possibly relative) Property href to an absolute URL."""
    if href.startswith("http"):
        return href
    return urljoin(_BASE_URL + "/", href.lstrip("/"))


def _card_to_listing(card) -> Listing:
    """Build one :class:`Listing` from a search-result card node."""
    anchor = card.find("a", href=_PROPERTY_HREF_RE)
    m = _PROPERTY_HREF_RE.search(anchor["href"])
    listing_id = m.group(2)

    title_el = _find_label(card, "Title") or card.find("h2")
    title = (
        title_el.get_text(" ", strip=True)
        if title_el is not None
        else (anchor.get("title") or "").strip()
    )

    currency = _label_text(card, "Currency")
    price_part = _label_text(card, "Price")
    price_text = f"{currency} {price_part}".strip() if price_part else ""

    area_text = _label_text(card, "Area")
    area_value, area_unit = _parse_area(area_text)

    created = _label_text(card, "Listing creation date")
    updated = _label_text(card, "Listing updated date")
    added_text = f"{created}{updated}" if updated else created

    image_url = ""
    for img in card.find_all("img"):
        if (img.get("aria-label") or "").strip().lower() == "listing photo":
            image_url = _img_src(img)
            break
    if not image_url:  # lazy-loaded cards may only expose media URLs anywhere
        for img in card.find_all("img"):
            candidate = _img_src(img)
            if "media.zameen.com" in candidate:
                image_url = candidate
                break

    return Listing(
        listing_id=listing_id,
        title=title,
        url=_absolute_property_url(m.group(1)),
        price_text=price_text,
        price_pkr=_parse_price_pkr(price_text),
        location=_label_text(card, "Location"),
        beds=_int_prefix(_label_text(card, "Beds")),
        baths=_int_prefix(_label_text(card, "Baths")),
        area_text=area_text or None,
        area_value=area_value,
        area_unit=area_unit,
        verified=bool(
            _find_label(card, "Verified badge")
            or _VERIFIED_TOKEN_RE.search(card.get_text(" ", strip=True))
        ),
        agent_tier=_badge_tier(card),
        promoted=_is_promoted(card),
        added_text=added_text,
        image_url=image_url,
    )


def parse_search(html: str) -> SearchResult:
    """Parse a Zameen.com search-results page into a :class:`SearchResult`.

    The current page number is not reliably marked up in Zameen's DOM, so
    ``page`` defaults to 1; :mod:`zameen_mcp.client` overrides it when it knows
    the requested page.

    >>> parse_search("<html><body><p>no results</p></body></html>")
    SearchResult(total_results=None, listings=[], page=1, next_page_url=None)
    """
    soup = _soup(html)

    total_results: Optional[int] = None
    h1 = soup.find("h1")
    if h1 is not None:
        m = _TOTAL_RE.search(h1.get_text(" ", strip=True))
        if m:
            total_results = int(m.group(1).replace(",", ""))

    listings = [_card_to_listing(card) for card in _card_nodes(soup)]

    next_anchor = soup.find(
        "a", attrs={"title": lambda t: t and t.strip().lower() == "next"}
    )
    next_page_url = (
        urljoin(_BASE_URL + "/", next_anchor["href"].lstrip("/"))
        if next_anchor is not None and next_anchor.get("href")
        else None
    )

    return SearchResult(
        total_results=total_results,
        listings=listings,
        page=1,
        next_page_url=next_page_url,
    )


def parse_listing_detail(html: str, url: str = "") -> dict:
    """Parse one Zameen.com property-detail page into a plain dict.

    Returned keys mirror the :class:`~zameen_mcp.models.Listing` fields minus
    ``property_type`` and ``purpose`` (those are context supplied by the
    caller): listing_id, title, url, price_text, price_pkr, location, beds,
    baths, area_text, area_value, area_unit, verified, agent_tier, promoted,
    added_text, image_url. Unknown values are None/empty.

    >>> parse_listing_detail("<html></html>")["listing_id"]
    ''
    """
    soup = _soup(html)

    canonical = soup.find("link", rel=lambda v: v and "canonical" in v)
    canonical_url = canonical.get("href", "").strip() if canonical else ""
    resolved_url = url or canonical_url

    listing_id = ""
    m = _PROPERTY_HREF_RE.search(resolved_url)
    if m:
        listing_id = m.group(2)
    else:
        title_tag = soup.title.get_text(" ", strip=True) if soup.title else ""
        id_match = re.search(r"\bID(\d+)\b", title_tag)
        if id_match:
            listing_id = id_match.group(1)

    h1 = soup.find("h1")
    title = h1.get_text(" ", strip=True) if h1 is not None else ""

    currency = _label_text(soup, "Currency")
    price_part = _label_text(soup, "Price")
    price_text = f"{currency} {price_part}".strip() if price_part else ""

    location = _label_text(soup, "Property header") or _label_text(soup, "Location")

    beds_text = _label_text(soup, "Beds")
    baths_text = _label_text(soup, "Baths")
    beds = _int_prefix(beds_text) if beds_text else None
    baths = _int_prefix(baths_text) if baths_text else None

    area_text = _label_text(soup, "Area") or _label_text(soup, "Property basic info")
    area_value, area_unit = _parse_area(area_text)

    added_text = ""
    details_ul = _find_label(soup, "Property details")
    detail_rows: dict[str, str] = {}
    if details_ul is not None:
        for row in details_ul.find_all("li"):
            cells = [c.strip() for c in row.get_text("|", strip=True).split("|")]
            if len(cells) >= 2:
                detail_rows[cells[0].lower()] = " ".join(cells[1:])
        if "price" in detail_rows and not price_text:
            price_text = detail_rows["price"]
        if "bedroom(s)" in detail_rows and beds is None:
            beds = _int_prefix(detail_rows["bedroom(s)"])
        if "bath(s)" in detail_rows and baths is None:
            baths = _int_prefix(detail_rows["bath(s)"])
        if "area" in detail_rows and not area_text:
            area_text = detail_rows["area"]
            area_value, area_unit = _parse_area(area_text)
        added_raw = detail_rows.get("added", "")
        if added_raw:
            added_text = f"Added: {added_raw}"
            updated_raw = detail_rows.get("updated", "")
            if updated_raw:
                added_text += f" (Updated: {updated_raw})"
    if not added_text:
        creation = _label_text(soup, "Creation date")
        if creation:
            added_text = f"Added: {creation}"

    image_url = ""
    for label in ("Cover Photo", "Listing photo"):
        img = _find_label(soup, label)
        if img is not None:
            image_url = _img_src(img)
            break
    if not image_url:
        og_image = soup.find("meta", attrs={"property": "og:image"})
        if og_image is not None:
            image_url = (og_image.get("content") or "").strip()

    page_text = soup.get_text(" ", strip=True)
    verified = bool(
        _find_label(soup, "Verified badge")
        or _VERIFIED_TOKEN_RE.search(page_text)
    )
    promoted = _is_promoted(soup)

    result = {
        "listing_id": listing_id,
        "title": title,
        "url": resolved_url,
        "price_text": price_text,
        "price_pkr": _parse_price_pkr(price_text),
        "location": location,
        "beds": beds,
        "baths": baths,
        "area_text": area_text or None,
        "area_value": area_value,
        "area_unit": area_unit,
        "verified": verified,
        "agent_tier": _badge_tier(soup),
        "promoted": promoted,
        "added_text": added_text,
        "image_url": image_url,
    }
    assert set(result) == set(_LISTING_FIELDS), "detail dict must mirror Listing fields"
    logger.debug(
        "parsed listing %s (%s chars of html)", listing_id or "?", len(html or "")
    )
    return result
