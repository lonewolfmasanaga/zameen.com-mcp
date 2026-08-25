"""Read-only HTTP client for Zameen.com research.

Composes URL building, fetching and parsing:

    from zameen_mcp.client import search
    result = search("Islamabad", "sale", "homes", beds_min=3, sort="price_asc")
    print(result.total_results, len(result.listings))

Only GET requests are ever issued; there are no account/agent/contact
endpoints here by design (see CONTRACTS.md guardrails).
"""

from __future__ import annotations

import logging
import re
import threading
import time
from typing import Dict, Optional, Tuple
from urllib.parse import urlencode, urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .models import SearchResult
from .parsers import parse_listing_detail, parse_search

logger = logging.getLogger(__name__)

__all__ = [
    "CITY_SLUGS",
    "TYPE_PATHS",
    "build_search_url",
    "configure_http",
    "fetch",
    "politeness_delay",
    "search",
    "get_listing",
    "set_politeness",
]

_BASE_URL = "https://www.zameen.com"

#: Optional authenticated session (set by session bootstrap / server startup).
#: When set, every fetch rides your logged-in cookies; when None, requests
#: are anonymous exactly as in v0.1.
_AUTH_SESSION: Optional["requests.Session"] = None


def set_auth_session(session: Optional["requests.Session"]) -> None:
    """Attach (or clear, passing None) the authenticated requests session."""
    global _AUTH_SESSION
    _AUTH_SESSION = session
    logger.info("auth session %s", "ENABLED" if session else "cleared")


def auth_enabled() -> bool:
    """True when fetches currently ride an authenticated session."""
    return _AUTH_SESSION is not None


def bootstrap_auth(session_module=None) -> bool:
    """Load saved login cookies (if any) into the client, silently.

    Called at server startup. Never raises: missing/expired sessions simply
    leave the client anonymous. Returns whether auth got enabled.
    """
    try:
        from . import session as _session
        s = (_session or session_module).requests_session()
        set_auth_session(s)
    except Exception as exc:  # noqa: BLE001 - auth must never break startup
        logger.warning("auth bootstrap skipped: %s", exc)
        set_auth_session(None)
    return _AUTH_SESSION is not None


# ----------------------------------------------------------- HTTP hardening --

#: Statuses worth retrying: rate limiting (429) and transient server faults.
_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})

#: Methods urllib3 may auto-retry. POST is deliberately excluded — a retried
#: POST could double-submit; this client only ever GETs anyway.
_RETRY_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE", "PUT", "DELETE"})

#: Hardened session built by :func:`configure_http` (lazily on first fetch).
_HTTP_SESSION: Optional["requests.Session"] = None

#: Per-request timeout in seconds; set alongside :func:`configure_http`.
_TIMEOUT: float = 45.0

_CONFIG_LOCK = threading.RLock()


def configure_http(
    max_retries: int = 2,
    backoff: float = 1.0,
    timeout: float = 45,
) -> "requests.Session":
    """(Re)build the module-level HTTP session with transient-fault retries.

    Installs a ``urllib3.util.retry.Retry`` policy that retries up to
    *max_retries* times (with exponential *backoff*, capped by urllib3's own
    limits) when Zameen answers 429/500/502/503/504, honouring any
    ``Retry-After`` header before falling back to computed backoff. POST is
    never retried. *timeout* becomes the per-request timeout used by every
    subsequent fetch.

    Safe to call repeatedly; each call swaps in a fresh session under a lock.
    Returns the new session.
    """
    global _HTTP_SESSION, _TIMEOUT
    retry = Retry(
        total=max(0, int(max_retries)),
        backoff_factor=float(backoff),
        status_forcelist=_RETRY_STATUSES,
        allowed_methods=_RETRY_METHODS,
        respect_retry_after_header=True,
        # Return the final response instead of raising MaxRetryError once
        # retries are exhausted; callers still see requests.HTTPError from
        # raise_for_status(), exactly as before hardening.
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session = requests.Session()
    session.mount("https://", adapter)
    session.mount("http://", adapter)

    with _CONFIG_LOCK:
        previous = _HTTP_SESSION
        _HTTP_SESSION = session
        _TIMEOUT = float(timeout)
    if previous is not None:
        try:
            previous.close()
        except Exception:  # noqa: BLE001 - closing must never break config
            pass
    logger.info(
        "http configured: retries=%s backoff=%ss timeout=%ss",
        max_retries,
        backoff,
        timeout,
    )
    return session


def _active_session() -> "requests.Session":
    """The hardened session, building it lazily with defaults on first use."""
    session = _HTTP_SESSION
    if session is not None:
        return session
    with _CONFIG_LOCK:
        if _HTTP_SESSION is None:
            configure_http()
        assert _HTTP_SESSION is not None  # for type checkers
        return _HTTP_SESSION


# ---------------------------------------------------------------- politeness --

#: Minimum seconds between consecutive fetches to zameen.com hosts. A basic
#: courtesy throttle; raise it via :func:`set_politeness` if asked to slow down.
_MIN_DELAY: float = 1.5

_POLITE_LOCK = threading.Lock()

#: Monotonic timestamp of the most recent zameen.com dispatch (None = never).
_LAST_FETCH_MONO: Optional[float] = None


def set_politeness(seconds: float) -> None:
    """Set the minimum delay (seconds) between zameen.com fetches."""
    global _MIN_DELAY
    seconds = float(seconds)
    if seconds < 0:
        raise ValueError(f"politeness delay must be >= 0, got {seconds!r}")
    with _POLITE_LOCK:
        _MIN_DELAY = seconds
    logger.debug("politeness delay set to %.3fs", seconds)


def politeness_delay() -> float:
    """Current minimum delay (seconds) between zameen.com fetches."""
    with _POLITE_LOCK:
        return _MIN_DELAY


def _is_zameen_url(url: str) -> bool:
    """True when *url* points at a zameen.com host (any subdomain)."""
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:  # malformed URL — let requests surface it later
        return False
    return host == "zameen.com" or host.endswith(".zameen.com")


def _throttle(url: str) -> None:
    """Sleep just enough to keep >= ``_MIN_DELAY`` since the last zameen hit.

    The wait happens under ``_POLITE_LOCK``, so concurrent worker threads are
    serialised into polite spacing rather than racing past it. Non-zameen URLs
    pass straight through.
    """
    global _LAST_FETCH_MONO
    if not _is_zameen_url(url):
        return
    with _POLITE_LOCK:
        now = time.monotonic()
        if _LAST_FETCH_MONO is not None:
            remaining = _MIN_DELAY - (now - _LAST_FETCH_MONO)
            if remaining > 0:
                logger.debug("politely sleeping %.3fs", remaining)
                time.sleep(remaining)
                now = time.monotonic()
        _LAST_FETCH_MONO = now


_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

#: lowercase city name -> Zameen city slug ("{Name}-{id}").
#: All entries verified against live pages; hyderabad-768 was checked and is
#: WRONG (redirects to Faisalabad Sargodha Road) — the correct slug is
#: "Hyderabad-30" (confirmed: h1 "352 Properties for Sale in Hyderabad").
CITY_SLUGS: Dict[str, str] = {
    "lahore": "Lahore-1",
    "karachi": "Karachi-2",
    "islamabad": "Islamabad-3",
    "rawalpindi": "Rawalpindi-41",
    "peshawar": "Peshawar-17",
    "faisalabad": "Faisalabad-16",
    "multan": "Multan-19",
    "gujranwala": "Gujranwala-327",
    "quetta": "Quetta-18",
    "sialkot": "Sialkot-480",
    "bahawalpur": "Bahawalpur-23",
    "abbottabad": "Abbottabad-385",
    "hyderabad": "Hyderabad-30",  # verified live 2026-08-22 (was NOT -768)
}

#: property-type key -> (sale_path, rent_path)
TYPE_PATHS: Dict[str, Tuple[str, str]] = {
    "homes": ("Homes", "Rentals"),
    "houses": ("Houses_Property", "Rentals_Houses_Property"),
    "flats": ("Flats_Apartments", "Rentals_Flats_Apartments"),
    "plots": ("Plots", "Rentals_Plots"),
    "commercial": ("Commercial", "Rentals_Commercial"),
    "rooms": ("Rooms", "Rentals_Rooms"),
}

_SORT_VALUES = ("price_asc", "price_desc", "date_desc")

#: One Marla in square metres (per CONTRACTS.md); Kanal = 20 Marla.
MARLA_SQM = 104.5159

_BARE_ID_RE = re.compile(r"\d{6,}")


def _format_sqm(value_sqm: float) -> str:
    """Render square metres as a compact query-param string."""
    rounded = round(value_sqm, 2)
    if abs(rounded - int(rounded)) < 1e-9:
        return str(int(rounded))
    return f"{rounded:g}"


def build_search_url(
    city_slug: str,
    type_path: str,
    purpose: str,
    *,
    page: int = 1,
    beds_min: Optional[int] = None,
    baths_min: Optional[int] = None,
    price_min: Optional[int] = None,
    price_max: Optional[int] = None,
    area_min: Optional[float] = None,
    area_max: Optional[float] = None,
    keywords: Optional[str] = None,
    sort: Optional[str] = None,
) -> str:
    """Build a Zameen.com search URL.

    ``city_slug`` is a value from :data:`CITY_SLUGS`, ``type_path`` the path
    part for the wanted listing type (from :data:`TYPE_PATHS`), ``purpose``
    either ``"sale"`` or ``"rent"``.

    NOTE on areas: the ``area_min`` / ``area_max`` arguments accept **Marla**
    floats and are converted internally to the square-metre values Zameen's
    ``area_min`` / ``area_max`` query params expect (Marla ~= 104.5159 sqm,
    Kanal = 20 Marla ~= 836.127 sqm).

    >>> build_search_url("Islamabad-3", "Homes", "sale", page=2, beds_min=3)
    'https://www.zameen.com/Homes/Islamabad-3-2.html?beds_in=3'
    """
    if purpose not in ("sale", "rent"):
        raise ValueError(f"purpose must be 'sale' or 'rent', got {purpose!r}")
    if sort is not None and sort not in _SORT_VALUES:
        raise ValueError(
            f"sort must be one of {_SORT_VALUES}, got {sort!r}"
        )
    if page < 1:
        raise ValueError(f"page must be >= 1, got {page!r}")

    base = f"{_BASE_URL}/{type_path}/{city_slug}-{page}.html"

    params: Dict[str, str] = {}
    if beds_min is not None:
        params["beds_in"] = str(int(beds_min))
    if baths_min is not None:
        params["baths_in"] = str(int(baths_min))
    if price_min is not None:
        params["price_min"] = str(int(price_min))
    if price_max is not None:
        params["price_max"] = str(int(price_max))
    # Area filters travel in square metres on the wire; callers pass Marla.
    if area_min is not None:
        params["area_min"] = _format_sqm(float(area_min) * MARLA_SQM)
    if area_max is not None:
        params["area_max"] = _format_sqm(float(area_max) * MARLA_SQM)
    if keywords:
        params["keywords"] = keywords
    if sort is not None:
        params["sort"] = sort

    return f"{base}?{urlencode(params)}" if params else base


def _get(url: str) -> tuple[str, str]:
    """GET *url* with browser-like headers; return ``(text, final_url)``.

    Rides the authenticated session when one is loaded (see
    :func:`set_auth_session`); otherwise uses the retry-hardened session from
    :func:`configure_http` — same headers either way. Fetches to zameen.com
    are spaced at least ``_MIN_DELAY`` apart (see :func:`set_politeness`).
    """
    _throttle(url)
    logger.debug("GET %s (auth=%s)", url, _AUTH_SESSION is not None)
    response = (_AUTH_SESSION or _active_session()).get(
        url,
        headers=_BROWSER_HEADERS,
        timeout=_TIMEOUT,
        allow_redirects=True,
    )
    response.raise_for_status()
    return response.text, response.url


def fetch(url: str) -> str:
    """Fetch *url* with browser-like User-Agent/Accept/Accept-Language headers.

    Timeout defaults to 45 seconds (:func:`configure_http` can change it);
    transient 429/5xx responses are retried automatically before any
    ``requests.HTTPError`` is raised.

    >>> fetch("https://example.com")  # doctest: +SKIP
    '<!doctype html>...'
    """
    text, _final_url = _get(url)
    return text


def search(
    city: str,
    purpose: str = "sale",
    property_type: str = "homes",
    *,
    page: int = 1,
    beds_min: Optional[int] = None,
    baths_min: Optional[int] = None,
    price_min: Optional[int] = None,
    price_max: Optional[int] = None,
    area_min: Optional[float] = None,
    area_max: Optional[float] = None,
    keywords: Optional[str] = None,
    sort: Optional[str] = None,
) -> SearchResult:
    """Run a search: build the URL, fetch it, parse it into a SearchResult.

    City names are matched case-insensitively against :data:`CITY_SLUGS`;
    ``property_type`` against :data:`TYPE_PATHS`. Every returned Listing gets
    its ``property_type`` and ``purpose`` fields set from this call's context.

    >>> result = search("islamabad")            # doctest: +SKIP
    >>> result.listings[0].purpose              # doctest: +SKIP
    'sale'
    """
    try:
        city_slug = CITY_SLUGS[city.strip().lower()]
    except KeyError:
        raise ValueError(
            f"unsupported city {city!r}; supported: {sorted(CITY_SLUGS)}"
        ) from None
    try:
        sale_path, rent_path = TYPE_PATHS[property_type.strip().lower()]
    except KeyError:
        raise ValueError(
            f"unsupported property_type {property_type!r}; "
            f"supported: {sorted(TYPE_PATHS)}"
        ) from None

    type_path = rent_path if purpose == "rent" else sale_path
    url = build_search_url(
        city_slug,
        type_path,
        purpose,
        page=page,
        beds_min=beds_min,
        baths_min=baths_min,
        price_min=price_min,
        price_max=price_max,
        area_min=area_min,
        area_max=area_max,
        keywords=keywords,
        sort=sort,
    )

    html = fetch(url)
    result = parse_search(html)
    result.page = page  # DOM has no reliable current-page marker
    for listing in result.listings:
        listing.property_type = property_type.strip().lower()
        listing.purpose = purpose
    logger.info(
        "search %s/%s/%s page %s -> %s listings (total %s)",
        city_slug,
        type_path,
        purpose,
        page,
        len(result.listings),
        result.total_results,
    )
    return result


def get_listing(listing_ref: str) -> dict:
    """Fetch and parse one listing detail page.

    Accepts a full Property URL or a bare numeric id; a bare id is resolved by
    constructing Zameen's minimal permissive Property URL
    (``https://www.zameen.com/Property/x-{id}-1-1.html``), which redirects to
    the listing's canonical URL. Returns the dict produced by
    :func:`zameen_mcp.parsers.parse_listing_detail`.

    >>> get_listing("54284067")           # doctest: +SKIP
    {'listing_id': '54284067', ...}
    """
    ref = (listing_ref or "").strip()
    if not ref:
        raise ValueError("listing_ref must be a Property URL or numeric id")

    if _BARE_ID_RE.fullmatch(ref):
        # NOTE: https://www.zameen.com/Property/{id} itself returns 404;
        # Zameen resolves the id from the slugless "x-{id}-1-1.html" form.
        html, final_url = _get(f"{_BASE_URL}/Property/x-{ref}-1-1.html")
        logger.info("resolved id %s -> %s", ref, final_url)
        return parse_listing_detail(html, url=final_url)

    if ref.startswith(("http://", "https://")) and "/Property/" in ref:
        html = fetch(ref)
        return parse_listing_detail(html, url=ref)

    raise ValueError(
        f"listing_ref must be a zameen.com Property URL or bare numeric id, "
        f"got {listing_ref!r}"
    )
