"""Test bootstrap.

If Agent A's real client.py has not landed yet, inject a temporary,
session-scoped stub module into sys.modules so the offline server tests can
run. The stub lives ONLY in memory (sys.modules) — no file is ever written to
src/, so there is zero collision risk with the real client.py arriving in
parallel.
"""

from __future__ import annotations

import sys
import types

import pytest

from zameen_mcp import client as _client


@pytest.fixture(autouse=True)
def _no_real_auth():
    """Hermeticity: real login cookies may exist on disk (data/session_state.json).

    server.py bootstraps them at import time; tests must always start and end
    with a clean, anonymous client regardless of what's on disk.
    """
    _client.set_auth_session(None)
    yield
    _client.set_auth_session(None)


def _ensure_client_stub() -> None:
    try:
        import zameen_mcp.client  # noqa: F401
        return  # real module exists — nothing to do
    except Exception:
        pass

    stub = types.ModuleType("zameen_mcp.client")

    stub.CITY_SLUGS = {
        "lahore": "Lahore-1", "karachi": "Karachi-2", "islamabad": "Islamabad-3",
        "rawalpindi": "Rawalpindi-41", "peshawar": "Peshawar-17",
        "faisalabad": "Faisalabad-16", "multan": "Multan-19",
        "gujranwala": "Gujranwala-327", "quetta": "Quetta-18",
        "sialkot": "Sialkot-480", "bahawalpur": "Bahawalpur-23",
        "abbottabad": "Abbottabad-385", "hyderabad": "Hyderabad-30",
    }
    stub.TYPE_PATHS = {
        "homes": ("Homes", "Rentals"),
        "houses": ("Houses_Property", "Rentals_Houses_Property"),
        "flats": ("Flats_Apartments", "Rentals_Flats_Apartments"),
        "plots": ("Plots", "Rentals_Plots"),
        "commercial": ("Commercial", "Rentals_Commercial"),
        "rooms": ("Rooms", "Rentals_Rooms"),
    }

    def build_search_url(city_slug, type_path, purpose, *, page=1, beds_min=None,
                         baths_min=None, price_min=None, price_max=None,
                         area_min=None, area_max=None, keywords=None, sort=None):
        return (f"https://www.zameen.com/{type_path}/{city_slug}-{page}.html"
                f"?stub=1&beds_min={beds_min}&area_min={area_min}"
                f"&keywords={keywords}&sort={sort}")

    def fetch(url):
        raise NotImplementedError("stub client: network disabled in tests")

    stub.build_search_url = build_search_url
    stub.fetch = fetch
    stub.search = lambda *a, **k: (_ for _ in ()).throw(NotImplementedError)
    stub.get_listing = lambda ref: (_ for _ in ()).throw(NotImplementedError)

    sys.modules["zameen_mcp.client"] = stub


_ensure_client_stub()
