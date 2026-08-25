"""FastMCP server exposing read-only Zameen.com research tools.

Tools:
- search_properties: structured search + badge-level post-filtering
- get_listing_details: one listing's detail page (URL or numeric id)
- list_supported_cities: verified city -> URL-slug map

Guardrails: strictly READ-ONLY. No tool posts data, messages agents, or
touches accounts. Client modules are imported lazily inside tool bodies so
this module imports cleanly even while sibling modules are being built.
"""

from __future__ import annotations

import json
import logging
from typing import List, Optional

try:  # fastmcp 2.x standalone package / mcp>=1.x vendored layout
    from fastmcp import FastMCP
except ImportError:  # pragma: no cover - legacy fallback
    from mcp.server.fastmcp import FastMCP

from .models import Listing

logger = logging.getLogger(__name__)

from . import client as _client_mod  # noqa: E402

_client_mod.bootstrap_auth()

mcp = FastMCP("zameen")

_MAX_PAGES = 3
_PURPOSES = ("sale", "rent")
_SORTS = ("price_asc", "price_desc", "date_desc")


def _json(payload) -> str:
    """Pretty JSON response body for MCP tool output."""
    return json.dumps(payload, indent=2, ensure_ascii=False)


def _post_filter(
    listings: List[Listing],
    *,
    verified_only: bool = False,
    agent_tier: Optional[str] = None,
    exclude_promoted: bool = False,
    max_price_pkr: Optional[int] = None,
) -> List[Listing]:
    """Badge/price-level filtering over parsed cards (CONTRACTS.md semantics).

    - verified_only: keep cards whose Verified badge is present
    - agent_tier: case-insensitive equality on card.agent_tier
    - exclude_promoted: drop hot / super hot promo cards
    - max_price_pkr: keep only parseable prices <= the cap
    """
    out: List[Listing] = []
    tier = (agent_tier or "").strip().lower()
    for l in listings:
        if verified_only and not l.verified:
            continue
        if tier and l.agent_tier.lower() != tier:
            continue
        if exclude_promoted and l.promoted:
            continue
        if max_price_pkr is not None and (
            l.price_pkr is None or l.price_pkr > max_price_pkr
        ):
            continue
        out.append(l)
    return out


def _collect_pages(**native) -> tuple:
    """Fetch up to _MAX_PAGES of results, dedupe by id, stop when exhausted.

    Returns (all_listings, total_results_from_first_page, pages_fetched).
    Raises whatever client.fetch raises (network/HTTP errors propagate).
    """
    from . import client, parsers

    all_listings: List[Listing] = []
    seen: set = set()
    total_results = None
    pages_fetched = 0

    for page in range(1, _MAX_PAGES + 1):
        url = client.build_search_url(page=page, **native)
        result = parsers.parse_search(client.fetch(url))
        pages_fetched += 1
        if total_results is None:
            total_results = result.total_results
        new_ids = {l.listing_id for l in result.listings} - seen
        for l in result.listings:
            if l.listing_id not in seen:
                seen.add(l.listing_id)
                all_listings.append(l)
        if not new_ids or not result.next_page_url:
            break
    return all_listings, total_results, pages_fetched


@mcp.tool()
def search_properties(
    city: str,
    purpose: str = "sale",
    property_type: str = "homes",
    min_beds: Optional[int] = None,
    max_price_pkr: Optional[int] = None,
    min_area_marla: Optional[float] = None,
    sort: Optional[str] = None,
    keywords: Optional[str] = None,
    verified_only: bool = False,
    agent_tier: Optional[str] = None,
    exclude_promoted: bool = False,
    limit: int = 10,
) -> str:
    """Search Zameen.com property listings and return normalized JSON cards.

    Use city names like "islamabad", "lahore", "karachi". purpose: sale|rent.
    property_type: homes|houses|flats|plots|commercial|rooms.
    Badge filters (verified_only, agent_tier e.g. "titanium", exclude_promoted,
    max_price_pkr) apply AFTER parsing over up to 3 result pages - these can
    express things Zameen's own UI cannot (e.g. verified listings only).
    min_beds/min_area_marla/keywords/sort are native site filters.
    Example: search_properties(city="lahore", purpose="sale",
    property_type="houses", min_beds=4, verified_only=True,
    agent_tier="titanium", max_price_pkr=200000000).
    """
    from . import client

    city_key = (city or "").strip().lower()
    slug = client.CITY_SLUGS.get(city_key)
    if slug is None:
        return _json({
            "error": f"unknown or unverified city: {city!r}",
            "supported_cities": sorted(client.CITY_SLUGS),
        })
    purpose_key = (purpose or "").strip().lower()
    if purpose_key not in _PURPOSES:
        return _json({"error": f"purpose must be one of {list(_PURPOSES)}"})
    type_key = (property_type or "").strip().lower()
    paths = client.TYPE_PATHS.get(type_key)
    if paths is None:
        return _json({
            "error": f"property_type must be one of {sorted(client.TYPE_PATHS)}"
        })
    if sort is not None and sort not in _SORTS:
        return _json({"error": f"sort must be one of {list(_SORTS)}"})

    index = 0 if purpose_key == "sale" else 1
    filters_applied = {
        "city": city_key,
        "purpose": purpose_key,
        "property_type": type_key,
        "min_beds": min_beds,
        "max_price_pkr": max_price_pkr,
        "min_area_marla": min_area_marla,
        "sort": sort,
        "keywords": keywords,
        "verified_only": verified_only,
        "agent_tier": agent_tier,
        "exclude_promoted": exclude_promoted,
        "limit": limit,
    }
    try:
        listings, total, pages_fetched = _collect_pages(
            city_slug=slug,
            type_path=paths[index],
            purpose=purpose_key,
            beds_min=min_beds,
            area_min=min_area_marla,
            keywords=keywords,
            sort=sort,
        )
    except Exception as exc:  # noqa: BLE001 - surfaced to the model as JSON
        logger.warning("search failed: %s", exc)
        return _json({"error": f"fetch failed: {exc}", **filters_applied})

    kept = _post_filter(
        listings,
        verified_only=verified_only,
        agent_tier=agent_tier,
        exclude_promoted=exclude_promoted,
        max_price_pkr=max_price_pkr,
    )
    for l in kept:
        l.property_type, l.purpose = type_key, purpose_key

    return _json({
        "total_results": total,
        "returned": len(kept[: max(limit, 0)]),
        "pages_fetched": pages_fetched,
        "filters_applied": filters_applied,
        "listings": [l.to_dict() for l in kept[: max(limit, 0)]],
    })


@mcp.tool()
def get_listing_details(listing: str) -> str:
    """Fetch full details for ONE Zameen.com property listing.

    Accepts a full Property URL or a bare numeric listing id such as
    "54646556". Read-only; never contacts the agent or modifies anything.
    """
    from . import client

    try:
        data = client.get_listing((listing or "").strip())
    except Exception as exc:  # noqa: BLE001
        logger.warning("get_listing failed: %s", exc)
        return _json({"error": f"fetch failed: {exc}", "listing": listing})
    return _json(data)


@mcp.tool()
def list_supported_cities() -> str:
    """List verified city slugs and property types usable by search_properties."""
    from . import client

    return _json({
        "cities": dict(sorted(client.CITY_SLUGS.items())),
        "property_types": sorted(client.TYPE_PATHS),
    })


# --------------------------------------------------------------------------
# Phase 3 tools: local watchlists, agent-message drafting, account status
# All are either purely local or draft-only. NOTHING is sent to Zameen.
# --------------------------------------------------------------------------

_WATCH_CRITERIA_KEYS = (
    "purpose", "property_type", "min_beds", "max_price_pkr",
    "min_area_marla", "keywords", "verified_only", "agent_tier",
    "exclude_promoted",
)


def _run_watch_search(criteria: dict):
    """Execute stored watch criteria through the search pipeline."""
    from . import client, parsers

    city = str(criteria.get("city", "")).strip().lower()
    slug = client.CITY_SLUGS.get(city)
    if slug is None:
        raise ValueError(f"watch criteria city invalid: {criteria.get('city')!r}")
    purpose = str(criteria.get("purpose", "sale"))
    type_key = str(criteria.get("property_type", "homes")).lower()
    paths = client.TYPE_PATHS.get(type_key)
    if paths is None:
        raise ValueError(f"watch criteria property_type invalid: {type_key!r}")
    url = client.build_search_url(
        slug, paths[0 if purpose == "sale" else 1], purpose,
        beds_min=criteria.get("min_beds"),
        area_min=criteria.get("min_area_marla"),
        keywords=criteria.get("keywords"),
        sort=criteria.get("sort"),
    )
    result = parsers.parse_search(client.fetch(url))
    from .server import _post_filter  # local import avoids cycles

    kept = _post_filter(
        result.listings,
        verified_only=bool(criteria.get("verified_only")),
        agent_tier=criteria.get("agent_tier"),
        exclude_promoted=bool(criteria.get("exclude_promoted")),
        max_price_pkr=criteria.get("max_price_pkr"),
    )
    for l in kept:
        l.property_type, l.purpose = type_key, purpose
    return result, kept


@mcp.tool()
def add_watch(name: str, city: str, purpose: str = "sale",
              property_type: str = "homes",
              min_beds: Optional[int] = None,
              max_price_pkr: Optional[int] = None,
              min_area_marla: Optional[float] = None,
              keywords: Optional[str] = None,
              verified_only: bool = False,
              agent_tier: Optional[str] = None,
              exclude_promoted: bool = False,
              seed_with_current: bool = True) -> str:
    """Create a named local watchlist from search criteria (stored on disk).

    Watches are re-checked later with check_watch; 'seed_with_current' runs
    the search once now so only NEW listings get reported in future checks.
    Nothing is saved to your Zameen account — this is a local file.
    """
    from . import watchlist

    criteria = {
        "city": city, "purpose": purpose, "property_type": property_type,
        "min_beds": min_beds, "max_price_pkr": max_price_pkr,
        "min_area_marla": min_area_marla, "keywords": keywords,
        "verified_only": verified_only, "agent_tier": agent_tier,
        "exclude_promoted": exclude_promoted,
    }
    seed_ids = None
    seeded_count = 0
    if seed_with_current:
        try:
            _result, kept = _run_watch_search(criteria)
            seed_ids = [l.listing_id for l in kept]
            seeded_count = len(seed_ids)
        except Exception as exc:  # noqa: BLE001
            return _json({"error": f"seeding search failed: {exc}",
                          "watch_not_created": True})
    try:
        entry = watchlist.add(name, criteria, seed_ids=seed_ids)
    except ValueError as exc:
        return _json({"error": str(exc)})
    return _json({"created": name, "criteria": entry["criteria"],
                  "seeded_listings": seeded_count,
                  "next_step": "run check_watch periodically"})


@mcp.tool()
def check_watch(name: str, limit: int = 20) -> str:
    """Re-run a saved watch's search and report NEW listings since last check.

    Read-only against Zameen; the only state kept is the local id list.
    """
    from . import watchlist

    entry = watchlist.get(name)
    if entry is None:
        known = sorted(watchlist.names())
        return _json({"error": f"no watch named {name!r}",
                      "existing_watches": known})
    criteria = entry["criteria"]
    try:
        result, kept = _run_watch_search(criteria)
    except Exception as exc:  # noqa: BLE001
        return _json({"error": f"search failed: {exc}", "watch": name})

    current_ids = [l.listing_id for l in kept]
    new_ids = watchlist.diff(entry.get("last_ids", []), current_ids)
    watchlist.record_check(name, current_ids)

    new_listings = [l.to_dict() for l in kept if l.listing_id in set(new_ids)]
    return _json({
        "watch": name,
        "total_results": result.total_results,
        "matching_now": len(kept),
        "new_since_last_check": len(new_listings),
        "listings": new_listings[: max(limit, 0)],
    })


@mcp.tool()
def remove_watch(name: str) -> str:
    """Delete a local watchlist by name."""
    from . import watchlist

    return _json({"removed": watchlist.remove(name)})


@mcp.tool()
def list_watches() -> str:
    """List local watchlists with their criteria and last-check times."""
    from . import watchlist

    return _json({"watches": watchlist.names()})


@mcp.tool()
def draft_agent_message(listing: str,
                        sender_name: str = "",
                        questions: Optional[List[str]] = None,
                        tone: str = "brief") -> str:
    """Draft (NOT send) a polite inquiry message to a listing's agent.

    Fetches the listing's details and composes a ready-to-send text for you
    to paste into WhatsApp/email or read out on a call. This tool NEVER sends
    anything to anyone — contacting the agent is deliberately a human action.
    """
    from . import client, messaging

    ref = (listing or "").strip()
    if not ref:
        return _json({"error": "listing URL or numeric id required"})
    try:
        detail = client.get_listing(ref)
    except Exception as exc:  # noqa: BLE001
        return _json({"error": f"fetch failed: {exc}"})
    try:
        draft = messaging.build_draft(detail, sender_name=sender_name,
                                      questions=questions, tone=tone)
    except ValueError as exc:
        return _json({"error": str(exc)})
    return _json(draft)


@mcp.tool()
def account_status() -> str:
    """Report whether an authenticated Zameen session is loaded.

    Auth is optional: searches work anonymously; a session (created via
    'python -m zameen_mcp.login') rides your cookies for personalized pages.
    No password is ever stored by this server.
    """
    from . import session as _session

    return _json(_session.status())


def main() -> None:
    """Run the MCP server over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
