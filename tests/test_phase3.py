"""Offline tests for Phase 3: watchlist, messaging drafts, session store."""

from __future__ import annotations

import json

import pytest

from zameen_mcp import client as client_mod
from zameen_mcp import messaging, server, watchlist


# ---------------------------------------------------------------- watches --

@pytest.fixture()
def wl(tmp_path, monkeypatch):
    monkeypatch.setattr(watchlist, "WATCHES_FILE", tmp_path / "watches.json")
    return tmp_path / "watches.json"


CRITERIA = {"city": "islamabad", "purpose": "sale", "property_type": "homes"}


def test_watch_add_get_remove(wl):
    watchlist.add("dha", CRITERIA, seed_ids=["1", "2"], path=wl)
    assert "dha" in watchlist.names(path=wl)
    assert watchlist.get("dha", path=wl)["last_ids"] == ["1", "2"]
    assert watchlist.remove("dha", path=wl) is True
    assert watchlist.remove("dha", path=wl) is False


def test_watch_duplicate_rejected(wl):
    watchlist.add("x", CRITERIA, path=wl)
    with pytest.raises(ValueError):
        watchlist.add("x", CRITERIA, path=wl)


def test_watch_blank_name_rejected(wl):
    with pytest.raises(ValueError):
        watchlist.add("  ", CRITERIA, path=wl)


def test_diff_order_preserved():
    assert watchlist.diff(["a", "b"], ["b", "c", "a", "d"]) == ["c", "d"]
    assert watchlist.diff([], ["x"]) == ["x"]


# ------------------------------------------------- server tool: add/check --

_FIXTURE_HTML = None


def _fixture_html() -> str:
    global _FIXTURE_HTML
    if _FIXTURE_HTML is None:
        import pytest
        from pathlib import Path

        path = (Path(__file__).resolve().parent.parent / "fixtures"
                / "search_islamabad.html")
        if not path.exists():
            pytest.skip("fixtures/ are local-only (gitignored)")
        _FIXTURE_HTML = path.read_text(encoding="utf-8")
    return _FIXTURE_HTML


@pytest.fixture()
def fake_search(monkeypatch):
    monkeypatch.setattr(client_mod, "build_search_url",
                        lambda *a, **kw: f"https://fake/{kw.get('page', 1)}")
    monkeypatch.setattr(client_mod, "fetch", lambda url: _fixture_html())


def _call(fn, *a, **kw):
    return json.loads(fn(*a, **kw))


def test_add_and_check_watch_flow(tmp_path, monkeypatch, fake_search):
    import zameen_mcp.watchlist as wlmod

    monkeypatch.setattr(wlmod, "WATCHES_FILE", tmp_path / "watches.json")

    data = _call(server.add_watch, "test-watch", city="islamabad")
    assert "error" not in data
    assert data["seeded_listings"] >= 10

    # Immediate re-check on the same fixture -> nothing new
    data2 = _call(server.check_watch, "test-watch")
    assert data2["new_since_last_check"] == 0
    assert data2["matching_now"] >= 10


def test_check_watch_detects_new_ids(tmp_path, monkeypatch, fake_search):
    import zameen_mcp.watchlist as wlmod

    monkeypatch.setattr(wlmod, "WATCHES_FILE", tmp_path / "watches.json")
    _call(server.add_watch, "w2", city="islamabad", seed_with_current=False)

    # Simulate previously-seen state missing the two newest listings
    from zameen_mcp.parsers import parse_search

    ids = [l.listing_id for l in parse_search(_fixture_html()).listings]
    wlmod.record_check("w2", ids[2:], path=tmp_path / "watches.json")

    data = _call(server.check_watch, "w2")
    assert data["new_since_last_check"] == 2


def test_add_watch_bad_city_reports_error(tmp_path, monkeypatch):
    import zameen_mcp.watchlist as wlmod

    monkeypatch.setattr(wlmod, "WATCHES_FILE", tmp_path / "w.json")
    data = _call(server.add_watch, "bad", city="atlantis")
    assert "error" in data and data["watch_not_created"] is True


# ---------------------------------------------------------------- drafts --

def test_draft_brief_shape():
    detail = {"title": "5 Marla House", "price_text": "PKR 2 Crore",
              "location": "DHA 6", "url": "https://z/P/x-123456-1-1.html",
              "listing_id": "123456"}
    d = messaging.build_draft(detail, sender_name="Ali")
    assert d["listing_id"] == "123456"
    assert "Ali" in d["message"] and "5 Marla House" in d["message"]
    assert "YOURSELF" in d["channel_hint"] or "never sends" in d["channel_hint"]


def test_draft_detailed_includes_url():
    d = messaging.build_draft({"title": "T", "url": "https://z/P/x-9-1-1.html"},
                              tone="detailed")
    assert "https://z/P/x-9-1-1.html" in d["message"]


def test_draft_custom_questions():
    d = messaging.build_draft({"title": "t"}, questions=["Price negotiable?"])
    assert "Price negotiable?" in d["message"]


def test_draft_bad_tone_raises():
    with pytest.raises(ValueError):
        messaging.build_draft({"title": "t"}, tone="shouty")


def test_server_draft_tool_offline(monkeypatch):
    monkeypatch.setattr(client_mod, "get_listing",
                        lambda ref: {"listing_id": ref, "title": "T",
                                     "url": "", "price_text": "",
                                     "location": ""})
    data = _call(server.draft_agent_message, "123456", sender_name="S")
    assert data["listing_id"] == "123456" and data["message"].startswith("Hello")


def test_server_list_watches(tmp_path, monkeypatch):
    import zameen_mcp.watchlist as wlmod

    monkeypatch.setattr(wlmod, "WATCHES_FILE", tmp_path / "w.json")
    wlmod.add("lw", CRITERIA, path=tmp_path / "w.json")
    data = _call(server.list_watches)
    assert "lw" in data["watches"]


def test_server_account_status_tool(monkeypatch, tmp_path):
    from zameen_mcp import session as sessmod

    monkeypatch.setattr(sessmod, "SESSION_FILE", tmp_path / "none.json")
    data = _call(server.account_status)
    assert data["logged_in"] is False


# ---------------------------------------------------------------- session --

def test_session_status_logged_out(tmp_path):
    from zameen_mcp import session

    st = session.status(path=tmp_path / "none.json")
    assert st["logged_in"] is False and st["cookie_count"] == 0


def test_session_save_roundtrip_and_expiry(tmp_path):
    from zameen_mcp import session

    p = tmp_path / "s.json"
    cookies = [
        {"name": "sess", "value": "v1", "domain": ".zameen.com",
         "path": "/", "expires": 4_000_000_000},
        {"name": "old", "value": "v2", "domain": ".zameen.com",
         "path": "/", "expires": 1_000_000},  # long expired
        {"name": "foreign", "value": "v3", "domain": ".google.com"},
    ]
    session.save_cookies(cookies, path=p)
    names = {c["name"] for c in session._live_cookies(path=p)}
    assert names == {"sess"}

    s = session.requests_session(path=p)
    assert s is not None and "sess" in s.cookies.get_dict()


def test_client_auth_toggle(monkeypatch, tmp_path):
    from zameen_mcp import session as sessmod

    class FakeResp:
        status_code = 200
        text = "<html></html>"
        url = "https://www.zameen.com/"

        def raise_for_status(self):
            pass

    # Phase 1: anonymous -> plain requests.get is used
    anon_hits = []
    monkeypatch.setattr(client_mod.requests, "get",
                        lambda url, **kw: anon_hits.append(url) or FakeResp())
    client_mod.fetch("https://www.zameen.com/x")
    assert anon_hits and anon_hits[0].endswith("/x")
    assert client_mod.auth_enabled() is False

    # Phase 2: authenticated -> the Session object's .get is used instead
    p = tmp_path / "s.json"
    sessmod.save_cookies([{"name": "sess", "value": "v",
                           "domain": ".zameen.com", "path": "/",
                           "expires": 4_000_000_000}], path=p)
    s = sessmod.requests_session(path=p)
    sess_hits = []
    monkeypatch.setattr(s, "get",
                        lambda url, **kw: sess_hits.append(url) or FakeResp())

    client_mod.set_auth_session(s)
    try:
        assert client_mod.auth_enabled() is True
        client_mod.fetch("https://www.zameen.com/y")
        assert sess_hits and not anon_hits[1:]  # session path, not requests
    finally:
        client_mod.set_auth_session(None)
    assert client_mod.auth_enabled() is False
