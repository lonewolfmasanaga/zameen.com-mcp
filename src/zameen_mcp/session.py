"""Authenticated-session management for zameen-mcp (Phase 3, Option B).

The USER logs in personally in a one-time Chromium window opened by::

    python -m zameen_mcp.login

Only Zameen.com session COOKIES are persisted (to ``data/session_state.json``).
The password is never typed into, seen by, or stored by any code in this
project. Treat ``data/session_state.json`` like a password: it grants access
to your Zameen account while the session is valid.

To wipe it: ``python -m zameen_mcp.login --logout`` or just delete the file.
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import List, Optional

import requests

logger = logging.getLogger(__name__)

def _data_dir() -> Path:
    """Per-user data dir: $ZAMEEN_MCP_HOME if set, else ~/.zameen-mcp."""
    import os

    env = os.environ.get("ZAMEEN_MCP_HOME")
    return Path(env) if env else Path.home() / ".zameen-mcp"


SESSION_FILE = _data_dir() / "session_state.json"

#: Persistent Chromium profile. Login state lives HERE on disk, so it survives
#: process kills / restarts — the login window is just a one-time setup step.
PROFILE_DIR = _data_dir() / "chrome-profile"

_ZAMEEN_URL = "https://www.zameen.com"


def has_session(path: Optional[Path] = None) -> bool:
    """True when the given store (default: real one) has live cookies."""
    return bool(_live_cookies(path))


def _load_raw(path: Optional[Path] = None) -> dict:
    p = Path(path or SESSION_FILE)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.warning("unreadable session file: %s", p)
        return {}
    return data if isinstance(data, dict) else {}


def _live_cookies(path: Optional[Path] = None) -> List[dict]:
    raw = (_load_raw(path).get("cookies") or []) if isinstance(_load_raw(path), dict) else []
    now = time.time()
    live = []
    for c in raw:
        expires = c.get("expires")
        if isinstance(expires, (int, float)) and expires > 0 and expires < now:
            continue  # expired
        if c.get("name") and c.get("value"):
            live.append(c)
    return live


def save_cookies(cookies: List[dict], path: Optional[Path] = None) -> Path:
    """Persist Playwright-format cookies; drops foreign domains."""
    kept = [
        {"name": c.get("name", ""), "value": c.get("value", ""),
         "domain": c.get("domain", ""), "path": c.get("path", "/"),
         "expires": c.get("expires", -1), "secure": c.get("secure", False),
         "httpOnly": c.get("httpOnly", False)}
        for c in cookies
        if "zameen.com" in (c.get("domain") or "")
    ]
    if not kept:
        raise ValueError("no zameen.com cookies found — did you actually log in?")
    p = Path(path or SESSION_FILE)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(
        {"cookies": kept, "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S")},
        indent=2), encoding="utf-8")
    logger.info("saved %d session cookies to %s", len(kept), p)
    return p


def clear(path: Optional[Path] = None) -> bool:
    p = Path(path or SESSION_FILE)
    if p.exists():
        p.unlink()
        return True
    return False


def requests_session(path: Optional[Path] = None) -> Optional[requests.Session]:
    """A requests.Session with saved cookies attached, or None if logged out."""
    cookies = _live_cookies(path)
    if not cookies:
        return None
    s = requests.Session()
    for c in cookies:
        s.cookies.set(c["name"], c["value"], domain=c.get("domain") or None,
                      path=c.get("path") or "/")
    return s


def status(path: Optional[Path] = None) -> dict:
    raw = _load_raw(path)
    return {
        "logged_in": has_session(path),
        "cookie_count": len(raw.get("cookies", [])) if raw else 0,
        "saved_at": raw.get("saved_at"),
    }


def open_login_window(timeout_seconds: int = 1800) -> int:
    """Open Chromium with a PERSISTENT profile at Zameen's login page.

    The USER logs in personally; the session lives in the on-disk profile
    (``data/chrome-profile``), so it survives process kills and restarts.
    This function can simply be re-run any time; if the profile already
    holds a valid session, Zameen shows the user as logged in immediately.
    Login is detected via Zameen's own embedded session state
    (``ready_to_login`` == anonymous). Returns cookies saved (0 on timeout).
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "playwright is not installed; run: "
            ".venv/Scripts/python.exe -m playwright install chromium"
        ) from exc

    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    print("Opening Chromium (persistent profile) at zameen.com/login ...",
          flush=True)
    saved = 0
    with sync_playwright() as pw:
        context = pw.chromium.launch_persistent_context(
            str(PROFILE_DIR),
            headless=False,
            viewport={"width": 1280, "height": 850},
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(f"{_ZAMEEN_URL}/login", wait_until="domcontentloaded")
        print("Window is open. Log in YOURSELF - this program never sees "
              "your password.", flush=True)
        print("The profile PERSISTS: even if this window is closed or the "
              "process is killed, your login survives on disk.", flush=True)
        print(f"Waiting for login (auto-saves once verified, max "
              f"{timeout_seconds}s)...", flush=True)

        def _site_says_logged_in() -> bool:
            """Ground truth from Zameen: the homepage embeds the session
            object; a real login carries a non-empty userEmail (and usually
            an accessToken). NOTE: the literal string 'ready_to_login' shows
            up in unrelated page payloads even when logged in, so it must
            NOT be used as the anonymity signal."""
            try:
                resp = context.request.get(
                    f"{_ZAMEEN_URL}/", timeout=30000,
                    headers={"Accept-Language": "en-US,en;q=0.9"})
                body = resp.text() or ""
            except Exception:  # noqa: BLE001
                return False
            email = re.search(r'"userEmail":"([^"@]+@[^"]+)"', body)
            token = re.search(r'"accessToken":"[^"]+"', body)
            return bool(email or token)

        deadline = time.time() + timeout_seconds
        try:
            while time.time() < deadline:
                if _site_says_logged_in():
                    time.sleep(2)  # let the session settle
                    cookies = context.cookies(_ZAMEEN_URL)
                    save_cookies(cookies)
                    saved = len([c for c in cookies
                                 if "zameen.com" in (c.get("domain") or "")])
                    print(f"Login VERIFIED - saved {saved} cookies AND the "
                          f"profile itself stays logged in.", flush=True)
                    break
                page.wait_for_timeout(5000)
            else:
                print("Timed out waiting for login (profile keeps its "
                      "state; re-run anytime).", flush=True)
        except Exception as exc:  # noqa: BLE001 - window closed by user
            print(f"Window closed ({type(exc).__name__}). The profile "
                  f"keeps its state - re-run this command to continue.",
                  flush=True)
        finally:
            try:
                context.close()
            except Exception:  # noqa: BLE001
                pass
    return saved


if __name__ == "__main__":
    import sys

    if "--logout" in sys.argv:
        removed = clear()
        print("Session cleared." if removed else "No session found.")
    else:
        n = open_login_window()
        print(f"Saved {n} cookies -> {SESSION_FILE}")
        print("The MCP server will pick these up on its next start.")
