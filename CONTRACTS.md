# zameen-mcp — Build Contracts (READ FULLY; agents must follow exactly)

Goal: an MCP server (stdio, FastMCP) exposing READ-ONLY research tools for
Zameen.com. Plain HTTP (requests + BeautifulSoup/lxml). No Selenium/Playwright
in the core. Python 3.11. Tests run OFFLINE against fixtures.

Working dir: `<project root>`
Venv python: `.venv/Scripts/python.exe` (deps pre-installed: requests, bs4,
lxml, pytest, mcp). Run tests: `.venv/Scripts/python.exe -m pytest -q`

## FILE OWNERSHIP — each agent writes ONLY its own files. Never edit another agent's file. Never edit pyproject.toml, CONTRACTS.md, or fixtures/ (orchestrator-owned).

| File | Owner |
|---|---|
| src/zameen_mcp/__init__.py | B |
| src/zameen_mcp/models.py | B |
| src/zameen_mcp/server.py | B |
| tests/test_server.py | B |
| src/zameen_mcp/parsers.py | A |
| src/zameen_mcp/client.py | A |
| tests/test_parsers.py | A |
| fixtures/listing_sample.html | A |
| README.md | C |
| docs/TOOLS.md | C |

Import direction: server → client → parsers → models. models.py must not import anything from this package.

## DATA CONTRACT (exact field names)

`Listing` dataclass (models.py):
```
listing_id: str            # numeric id from URL, e.g. "54646556"
title: str
url: str                   # absolute https://www.zameen.com/Property/...
price_text: str            # as displayed, e.g. "PKR 68 Thousand"
price_pkr: Optional[int]   # parsed numeric PKR; None if unparseable
location: str
beds: Optional[int]
baths: Optional[int]
area_text: Optional[str]   # e.g. "12 Marla"
area_value: Optional[float]
area_unit: Optional[str]   # "Marla"|"Kanal"|"Sq. Yd."|"Sq. Ft."
property_type: str = ""    # set by client from search context
purpose: str = ""          # "sale"|"rent", set by client
verified: bool = False     # "Verified" badge present on card
agent_tier: str = ""       # "" if none else lowercase e.g. "titanium"
promoted: bool = False     # "super hot" or "hot" promo badge present
added_text: str = ""       # raw e.g. "Added: 7 hours ago(Updated: 7 hours ago)"
image_url: str = ""
```
`SearchResult` dataclass: `total_results: Optional[int]`, `listings: List[Listing]`, `page: int`, `next_page_url: Optional[str]`

PKR parsing rule: "Thousand" ×1_000, "Lakh" ×100_000, "Crore" ×10_000_000,
"Arab" ×1_000_000_000; bare digits stay as-is. Strip commas.

## PUBLIC API SIGNATURES (exact)

parsers.py:
- `parse_search(html: str) -> SearchResult`
- `parse_listing_detail(html: str, url: str = "") -> dict`  # keys mirror Listing fields (minus property_type/purpose)

client.py:
- `CITY_SLUGS: Dict[str, str]` — keys lowercase city names. Confirmed: lahore→"Lahore-1", karachi→"Karachi-2", islamabad→"Islamabad-3", rawalpindi→"Rawalpindi-41", peshawar→"Peshawar-17", faisalabad→"Faisalabad-16", multan→"Multan-19", gujranwala→"Gujranwala-327", quetta→"Quetta-18", sialkot→"Sialkot-480", bahawalpur→"Bahawalpur-23", abbottabad→"Abbottabad-385". VERIFY hyderabad (probe once with fetch(); drop entry if wrong).
- `TYPE_PATHS: Dict[str, Tuple[str, str]]` — key → (sale_path, rent_path): homes→("Homes","Rentals"), houses→("Houses_Property","Rentals_Houses_Property"), flats→("Flats_Apartments","Rentals_Flats_Apartments"), plots→("Plots","Rentals_Plots"), commercial→("Commercial","Rentals_Commercial"), rooms→("Rooms","Rentals_Rooms"). Upper portions etc optional extras.
- `build_search_url(city_slug, type_path, purpose, *, page=1, beds_min=None, baths_min=None, price_min=None, price_max=None, area_min=None, area_max=None, keywords=None, sort=None) -> str`
  Format: `https://www.zameen.com/{path}/{city_slug}-{page}.html` where path comes
  from TYPE_PATHS[purpose]. Params: beds_in, baths_in, price_min, price_max,
  area_min, area_max, keywords, sort (values: price_asc, price_desc, date_desc).
  Omit unset params. NOTE area params are in square metres (Marla≈104.5159,
  Kanal≈836.127) — accept marla floats here and convert internally; document it.
- `fetch(url: str) -> str` — GET with browser-like User-Agent + Accept +
  Accept-Language headers, timeout=45, raise_for_status, return response.text.
- `search(...)` convenience composing build_search_url + fetch + parse_search;
  sets property_type/purpose on listings.
- `get_listing(listing_ref: str) -> dict` — accepts full URL or bare numeric id
  (bare id → look up canonical URL by fetching `https://www.zameen.com/Property/{id}` redirect target or constructing minimal URL); returns parse_listing_detail output.

server.py (FastMCP, name="zameen"):
- Tools (all return JSON strings, indent=2):
  - `search_properties(city, purpose="sale", property_type="homes", min_beds=None, max_price_pkr=None, min_area_marla=None, sort=None, keywords=None, verified_only=False, agent_tier=None, exclude_promoted=False, limit=10)`
    Post-filters (verified_only, agent_tier, exclude_promoted, max_price_pkr)
    apply over fetched pages, cap 3 pages fetched. Returns JSON:
    {total_results, returned, filters_applied, listings:[...]}
  - `get_listing_details(listing: str)` — accepts URL or numeric id.
  - `list_supported_cities()` — static dict dump.
- Guardrails: read-only tools only. No tool may POST, message agents, or touch accounts.

## PARSING ANCHORS (ground truth from live HTML)

- Cards are `<li>` elements containing `<a>` whose href matches
  `https://www\.zameen\.com/Property/.+-(\d{6,})-\d+-\d+\.html` — capture group = listing_id.
- Badge tokens appear verbatim inside the card DOM/text: `Verified`,
  `Titanium`, `super hot`, `hot` (case-sensitive tokens; beware substring
  collisions — match token-wise, not naive substring on whole page).
- Price line begins with `PKR`.
- Beds/baths: numeric tiles rendered near bed/bath icon images (img alt or
  aria-label contains "bed"/"bath"); inspect the fixture for exact markup.
- Area regex: `([\d.,]+)\s*(Marla|Kanal|Sq\. ?Yd\.|Sq\. ?Ft\.)`
- Total count: text like `1,775 Properties for Sale in Islamabad` (h1 region);
  strip commas → int.
- Next page: `<a>` titled `Next`.

## FIXTURES
- `fixtures/search_islamabad.html` EXISTS (real page: Islamabad Homes sale, beds_in=3, sort=price_asc, 1.3MB).
- Agent A: fetch ONE Property detail URL found in that fixture with client.fetch()
  and save byte-exact to `fixtures/listing_sample.html`. If fetch fails, report
  back instead of fabricating.

## STYLE RULES
- Stdlib + requests/bs4/lxml only. Type hints + docstrings (with one usage
  example) on every public function. No prints in library code (use logging).
- Deterministic parsing; never hardcode listing-specific values in library code.
- DONE means: your files written AND `.venv/Scripts/python.exe -m pytest -q tests/<your test file>` passes AND `python -m compileall src` clean.
