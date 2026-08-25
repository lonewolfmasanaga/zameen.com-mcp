# MCP Tool Reference — zameen-mcp

Reference for all **9 tools** exposed by the `zameen` MCP server
(`src/zameen_mcp/server.py`). This document tracks the actual signatures in
code; if they ever drift, code wins and this file needs a PR.

All tools:

- are **read-only** against Zameen.com — only GET requests are ever issued;
  nothing posts data, messages agents, or touches accounts;
- return pretty-printed JSON (`indent=2`) as their entire response body;
- never raise across the wire — failures come back as JSON objects carrying
  an `"error"` key (see [Error shapes](#error-shapes)).

---

## Conventions

### Listing card fields

Every listing card (search results, watch hits) serializes the same 18 fields
(`zameen_mcp.models.Listing.to_dict()`):

| Field | Type | Notes |
|---|---|---|
| `listing_id` | string | numeric id, e.g. `"54646556"` |
| `title` | string | card heading |
| `url` | string | absolute Property URL |
| `price_text` | string | display form, e.g. `"PKR 4.15 Crore"` (may be empty) |
| `price_pkr` | int \| null | parsed integer PKR; `null` if unparseable |
| `location` | string | e.g. `"DHA Phase 6, DHA Defence"` |
| `beds`, `baths` | int \| null | `null` when not shown on the card |
| `area_text` | string \| null | display form, e.g. `"12 Marla"` |
| `area_value` | float \| null | numeric part of `area_text` |
| `area_unit` | string \| null | `Marla`, `Kanal`, `Sq. Yd.`, `Sq. Ft.` … |
| `property_type` | string | set from your call's context (`homes`, `houses`, …) |
| `purpose` | string | `sale` or `rent` (from your call's context) |
| `verified` | bool | Verified badge present on the card |
| `agent_tier` | string | lowercased tier: `titanium`, `platinum`, `gold`, `silver`, `bronze`; `""` when none |
| `promoted` | bool | paid promo (`hot` / `super hot`) |
| `added_text` | string | raw date line, e.g. `"Added: 7 hours ago(Updated: 7 hours ago)"` |
| `image_url` | string | thumbnail URL; `""` when absent |

Missing page data degrades to `null` / empty strings — parsers are None-safe.

### Search pagination behaviour

`search_properties` fetches **up to 3 result pages** per call, dedupes cards
by `listing_id`, and stops early when a page yields no new ids or there is no
next-page link. Badge-level filters then run over everything fetched.
Each HTTP request has a 45-second timeout.

---

## Research tools

### `search_properties`

Structured search with native site filters plus post-filtering Zameen's own UI
cannot express.

```python
search_properties(
    city: str,
    purpose: str = "sale",
    property_type: str = "homes",
    min_beds: int | None = None,
    max_price_pkr: int | None = None,
    min_area_marla: float | None = None,
    sort: str | None = None,
    keywords: str | None = None,
    verified_only: bool = False,
    agent_tier: str | None = None,
    exclude_promoted: bool = False,
    limit: int = 10,
) -> str
```

| Param | Type | Default | Notes |
|---|---|---|---|
| `city` | string | *required* | case-insensitive key of `list_supported_cities`, e.g. `"islamabad"`, `"lahore"` |
| `purpose` | string | `"sale"` | `sale` or `rent` |
| `property_type` | string | `"homes"` | `homes`, `houses`, `flats`, `plots`, `commercial`, `rooms` |
| `min_beds` | int | `null` | **native** site filter (`beds_in` URL param) |
| `max_price_pkr` | int | `null` | **post-filter**: keep parseable prices ≤ cap |
| `min_area_marla` | float | `null` | **native**; converted to square metres (~104.5159/marla) for the URL |
| `sort` | string | `null` | `price_asc`, `price_desc`, `date_desc` (**native**) |
| `keywords` | string | `null` | e.g. `"instalment"`, `"furnished"` (**native**) |
| `verified_only` | bool | `false` | keep only Verified-badge cards |
| `agent_tier` | string | `null` | case-insensitive equality, e.g. `"titanium"`, `"titanium plus"` |
| `exclude_promoted` | bool | `false` | drop `hot` / `super hot` promo cards |
| `limit` | int | `10` | max listings returned (applied after filtering; ≤ 0 → empty list) |

Native filters map onto Zameen search-URL params; badge filters
(`verified_only`, `agent_tier`, `exclude_promoted`, `max_price_pkr`) apply
**after parsing**, across up to 3 fetched pages.

Example invocation:

```json
{
  "city": "lahore", "purpose": "sale", "property_type": "houses",
  "min_beds": 4, "min_area_marla": 10, "max_price_pkr": 200000000,
  "verified_only": true, "agent_tier": "titanium",
  "exclude_promoted": true, "limit": 15
}
```

Response shape:

```json
{
  "total_results": 1775,
  "returned": 3,
  "pages_fetched": 3,
  "filters_applied": {
    "city": "lahore", "purpose": "sale", "property_type": "houses",
    "min_beds": 4, "max_price_pkr": 200000000, "min_area_marla": 10,
    "sort": null, "keywords": null,
    "verified_only": true, "agent_tier": "titanium",
    "exclude_promoted": true, "limit": 15
  },
  "listings": [ { "...": "Listing card fields (see above)" } ]
}
```

### `get_listing_details`

Fetch and parse one listing's full detail page.

```python
get_listing_details(listing: str) -> str
```

| Param | Type | Notes |
|---|---|---|
| `listing` | string | Full Property URL **or** bare numeric id of 6+ digits (e.g. `"54646556"`). A bare id is resolved via Zameen's minimal permissive URL `https://www.zameen.com/Property/x-{id}-1-1.html`, which redirects to the canonical page |

```json
{ "listing": "54646556" }
```

Success returns one JSON object mirroring the Listing card fields above,
minus `property_type` / `purpose` (those are search-context fields).
Unknown values come back `null`/empty rather than erroring.

### `list_supported_cities`

No parameters. Returns the verified city→slug map and property types used by
`search_properties`:

```json
{
  "cities": {
    "abbottabad": "Abbottabad-385", "bahawalpur": "Bahawalpur-23",
    "faisalabad": "Faisalabad-16", "gujranwala": "Gujranwala-327",
    "hyderabad": "Hyderabad-30", "islamabad": "Islamabad-3",
    "karachi": "Karachi-2", "lahore": "Lahore-1", "multan": "Multan-19",
    "peshawar": "Peshawar-17", "quetta": "Quetta-18",
    "rawalpindi": "Rawalpindi-41", "sialkot": "Sialkot-480"
  },
  "property_types": ["commercial", "flats", "homes", "houses", "plots", "rooms"]
}
```

(The city list grows as slugs are verified against live pages — treat the tool
output as authoritative.)

---

## Watchlist tools (local-only)

Watches are **our** feature, not Zameen's account feature: criteria live in a
local JSON file under `$ZAMEEN_MCP_HOME` (default `~/.zameen-mcp/watches.json`)
and nothing is ever written to Zameen.com.

### `add_watch`

Create a named local watch from search criteria.

```python
add_watch(
    name: str,
    city: str,
    purpose: str = "sale",
    property_type: str = "homes",
    min_beds: int | None = None,
    max_price_pkr: int | None = None,
    min_area_marla: float | None = None,
    keywords: str | None = None,
    verified_only: bool = False,
    agent_tier: str | None = None,
    exclude_promoted: bool = False,
    seed_with_current: bool = True,
) -> str
```

Filter params have identical semantics to `search_properties`.
`seed_with_current=True` (default) runs the search once now so that future
`check_watch` calls report only listings you haven't seen.

Success:

```json
{
  "created": "dha-6-houses",
  "criteria": { "...": "echoed criteria" },
  "seeded_listings": 25,
  "next_step": "run check_watch periodically"
}
```

Errors: blank/duplicate name → `{"error": "watch 'dha-6-houses' already exists; remove it first"}`;
seeding search failure → `{"error": "seeding search failed: ...", "watch_not_created": true}`.

### `check_watch`

Re-run a saved watch's search and report **new** listings since last check.
Read-only against Zameen; the only state kept is the local id list.

```python
check_watch(name: str, limit: int = 20) -> str
```

```json
{
  "watch": "dha-6-houses",
  "total_results": 1802,
  "matching_now": 31,
  "new_since_last_check": 2,
  "listings": [ { "...": "Listing card fields (see above)" } ]
}
```

`listings` holds only the new cards, capped at `limit`. Each check records the
seen ids locally (`last_ids`, `last_checked_at`).

### `list_watches`

No parameters. Summary view of saved watches:

```json
{
  "watches": {
    "dha-6-houses": {
      "criteria": { "...": "stored criteria" },
      "created_at": "2026-08-22T14:03:11",
      "last_checked_at": "2026-08-24T09:12:40",
      "known_listing_count": 25
    }
  }
}
```

### `remove_watch`

Delete a local watch by name.

```python
remove_watch(name: str) -> str   # -> {"removed": true}  (false if it didn't exist)
```

---

## Messaging & account tools

### `draft_agent_message`

Draft (**not send**) a polite inquiry message to a listing's agent.

```python
draft_agent_message(
    listing: str,
    sender_name: str = "",
    questions: list[str] | None = None,
    tone: str = "brief",
) -> str
```

| Param | Type | Default | Notes |
|---|---|---|---|
| `listing` | string | *required* | Property URL or bare numeric id (same as `get_listing_details`) |
| `sender_name` | string | `""` | included in the greeting when non-empty |
| `questions` | list[string] | `null` | custom questions; defaults to availability + visit scheduling |
| `tone` | string | `"brief"` | `brief` or `detailed` |

The listing detail page is fetched read-only, then the text is composed
locally — **this tool NEVER sends anything to anyone**; contacting the agent
is deliberately a human action (WhatsApp/call/email).

```json
{
  "channel_hint": "whatsapp_or_call — send it YOURSELF; this tool never sends",
  "tone": "brief",
  "message": "Hello.\nI'm interested in: 1 Kanal House ...\n- Is this property still available?\n- Can I schedule a visit this week?",
  "listing_id": "54646556",
  "listing_url": "https://www.zameen.com/Property/...html",
  "questions_used": ["Is this property still available?", "Can I schedule a visit this week?"]
}
```

### `account_status`

Report whether an authenticated Zameen session is loaded. Auth is optional:
searches work anonymously; a session (created via the optional login flow,
see docs/DEPLOYMENT.md) rides your cookies for personalized pages. No password
is ever stored.

```python
account_status() -> str   # no parameters
```

```json
{
  "logged_in": false,
  "cookie_count": 0,
  "saved_at": null
}
```

---

## Error shapes

Tools validate inputs **before any network request** where possible, and every
caught failure comes back as a JSON object with a top-level `"error"` string.
Nothing else about the shape changes: success keys are simply replaced by
`"error"` plus whatever echo/context keys the tool adds.

| Tool | Situation | Body |
|---|---|---|
| `search_properties` | unknown city | `{"error": "unknown or unverified city: 'x'", "supported_cities": [...], ...}` |
| | bad `purpose` | `{"error": "purpose must be one of ['sale', 'rent']"}` |
| | bad `property_type` | `{"error": "property_type must be one of ['commercial', 'flats', 'homes', 'houses', 'plots', 'rooms']"}` |
| | bad `sort` | `{"error": "sort must be one of ['date_desc', 'price_asc', 'price_desc']"}` |
| | network / HTTP status | `{"error": "fetch failed: <exception>", "city": ..., "purpose": ..., "property_type": ..., ...all filters echoed}` |
| `get_listing_details` | network / HTTP status | `{"error": "fetch failed: <exception>", "listing": "<your input>"}` |
| `add_watch` | blank or duplicate name | `{"error": "watch name must be non-empty"}` / `{"error": "watch 'x' already exists; remove it first"}` |
| | seeding search fails | `{"error": "seeding search failed: <exception>", "watch_not_created": true}` — nothing is stored |
| `check_watch` | unknown name | `{"error": "no watch named 'x'", "existing_watches": [...]}` |
| | search fails | `{"error": "search failed: <exception>", "watch": "x"}` |
| `draft_agent_message` | empty `listing` | `{"error": "listing URL or numeric id required"}` |
| | network / HTTP status | `{"error": "fetch failed: <exception>"}` |
| | invalid `tone` | `{"error": "tone must be one of ('brief', 'detailed'), got 'x'"}` |
| `list_supported_cities`, `list_watches`, `remove_watch`, `account_status` | — | pure local reads; no error cases in practice |

Notes:

- Validation errors (`purpose`, `property_type`, `sort`, city) return before
  any HTTP request is made.
- `fetch failed:` bodies embed the underlying exception text, e.g.
  `"fetch failed: 404 Client Error: Not Found for url: https://..."`.
- A `fetch failed` from `search_properties` echoes your full
  `filters_applied` block so the caller can retry with corrected inputs.

---

## Filter cheat-sheet (natural language → parameters)

| User says | Parameters |
|---|---|
| "verified listings only" | `verified_only: true` |
| "only Titanium agencies" | `agent_tier: "titanium"` |
| "Titanium Plus only" | `agent_tier: "titanium plus"` |
| "skip the sponsored/ads" | `exclude_promoted: true` |
| "under 2 crore" | `max_price_pkr: 200000000` |
| "50 lakh max rent" | `max_price_pkr: 5000000` |
| "at least 10 marla" | `min_area_marla: 10` |
| "4+ beds, newest first" | `min_beds: 4, sort: "date_desc"` |
| "cheap flats first" | `property_type: "flats", sort: "price_asc"` |

## PKR units

| Unit in price text | Multiplier |
|---|---|
| Thousand | × 1,000 |
| Lakh | × 100,000 |
| Crore | × 10,000,000 |
| Arab | × 1,000,000,000 |

`price_text` keeps the display form ("PKR 2.1 Arab"); `price_pkr` carries the
parsed integer (`2100000000`). `price_pkr` is `null` if unparseable.

## Area units

Zameen search URLs encode area ranges in **square metres**; this server accepts
Marla/Kanal from you and converts:

| Unit | sq metres (used by zameen URLs) |
|---|---|
| 1 Marla | ≈ 104.5159 |
| 1 Kanal | = 20 Marla ≈ 836.127 |

Card parsing returns the display unit verbatim (`Marla`, `Kanal`, `Sq. Yd.`,
`Sq. Ft.`) in `area_unit` with the numeric value in `area_value`.
