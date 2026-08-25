# MCP Tool Reference — zameen-mcp

All tools are **read-only**, return `application/json` (pretty-printed, indent=2),
and never touch accounts or send messages.

---

## `search_properties`

Run a structured search on Zameen.com and return normalized listing cards.

### Parameters

| Param | Type | Default | Notes |
|---|---|---|---|
| `city` | string | *required* | e.g. `"islamabad"`, `"lahore"` (case-insensitive) |
| `purpose` | string | `"sale"` | `"sale"` or `"rent"` |
| `property_type` | string | `"homes"` | `homes`, `houses`, `flats`, `plots`, `commercial`, `rooms` |
| `min_beds` | int | `null` | native `beds_in` filter |
| `max_price_pkr` | int | `null` | post-filter on parsed price |
| `min_area_marla` | float | `null` | converted internally to sq-m (~104.5159/marla) |
| `sort` | string | `null` | `price_asc`, `price_desc`, `date_desc` |
| `keywords` | string | `null` | e.g. `"instalment"`, `"furnished"` |
| `verified_only` | bool | `false` | keep only cards with a Verified badge |
| `agent_tier` | string | `null` | case-insensitive tier match: `"titanium"`, `"titanium plus"` |
| `exclude_promoted` | bool | `false` | drop `hot` / `super hot` paid promos |
| `limit` | int | `10` | max listings returned |

Native filters map onto Zameen's own search URL params; badge-based filters
(`verified_only`, `agent_tier`, `exclude_promoted`, `max_price_pkr`) are applied
after parsing across up to **3 fetched pages**.

### Example invocation

```json
{
  "city": "lahore",
  "purpose": "sale",
  "property_type": "houses",
  "min_beds": 4,
  "min_area_marla": 10,
  "max_price_pkr": 200000000,
  "verified_only": true,
  "agent_tier": "titanium",
  "exclude_promoted": true,
  "limit": 15
}
```

### Response shape

```json
{
  "total_results": 1775,
  "returned": 3,
  "filters_applied": {
    "city": "lahore", "purpose": "sale", "property_type": "houses",
    "min_beds": 4, "max_price_pkr": 200000000, "min_area_marla": 10,
    "verified_only": true, "agent_tier": "titanium", "exclude_promoted": true
  },
  "listings": [
    {
      "listing_id": "54646556",
      "title": "12 Marla house ...",
      "url": "https://www.zameen.com/Property/...-54646556-9850-1.html",
      "price_text": "PKR 4.15 Crore",
      "price_pkr": 41500000,
      "location": "DHA Phase 6, DHA Defence",
      "beds": 4, "baths": 5,
      "area_text": "12 Marla", "area_value": 12.0, "area_unit": "Marla",
      "property_type": "houses", "purpose": "sale",
      "verified": true, "agent_tier": "titanium", "promoted": false,
      "added_text": "Added: 7 hours ago(Updated: 7 hours ago)",
      "image_url": "https://media.zameen.com/thumbnails/...jpeg"
    }
  ]
}
```

---

## `get_listing_details`

Fetch and parse one listing's full detail page.

| Param | Type | Notes |
|---|---|---|
| `listing` | string | Full Property URL **or** bare numeric id (e.g. `"54646556"`) |

### Example

```json
{ "listing": "54646556" }
```

Response mirrors the `Listing` fields above plus detail-page extras
(description text, feature list, agent info, photo URLs) where present.

---

## `list_supported_cities`

No parameters. Returns the verified city→slug map used by `search_properties`,
e.g. `{ "lahore": "Lahore-1", "karachi": "Karachi-2", "islamabad": "Islamabad-3", ... }`.

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
