"""Live E2E smoke test of the zameen MCP tool layer (hits real site)."""
import json
import sys

sys.path.insert(0, "src")
from zameen_mcp import server  # noqa: E402


def run(label, fn, *a, **kw):
    print(f"\n=== {label} ===")
    raw = fn(*a, **kw)
    data = json.loads(raw)
    print(json.dumps(data, indent=2)[:2600])
    return data


cities = run("list_supported_cities", server.list_supported_cities)

search = run(
    "search_properties: Islamabad homes, 3+ beds, VERIFIED + TITANIUM only",
    server.search_properties,
    city="islamabad", purpose="sale", property_type="homes", min_beds=3,
    verified_only=True, agent_tier="titanium", exclude_promoted=True, limit=5,
)

if search.get("listings"):
    first = search["listings"][0]["listing_id"]
    run("get_listing_details", server.get_listing_details, first)
else:
    # fall back to a plain search so the detail tool still gets exercised
    plain = run("fallback plain search", server.search_properties,
                city="islamabad", limit=3)
    if plain.get("listings"):
        run("get_listing_details", server.get_listing_details,
            plain["listings"][0]["listing_id"])

print("\nSMOKE DONE")
