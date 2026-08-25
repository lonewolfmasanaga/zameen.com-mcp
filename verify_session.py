"""Verify the persisted Zameen session in data/chrome-profile (headless).

If authenticated, snapshots the session cookies for the plain-HTTP fetcher
via session.save_cookies(). Safe to re-run any time.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from playwright.sync_api import sync_playwright  # noqa: E402

from zameen_mcp import session as sess  # noqa: E402


def main() -> None:
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            str(sess.PROFILE_DIR), headless=True)
        try:
            body = ctx.request.get(
                "https://www.zameen.com/", timeout=30000,
                headers={"Accept-Language": "en-US,en;q=0.9"}).text() or ""
            email = re.search(r'"userEmail":"([^"@]+@[^"]+)"', body)
            token = re.search(r'"accessToken":"([^"]+)"', body)
            print("userEmail:", email.group(1) if email else None)
            print("accessToken present:", bool(token))
            if email or token:
                cookies = ctx.cookies("https://www.zameen.com")
                path = sess.save_cookies(cookies)
                n = len([c for c in cookies
                         if "zameen.com" in (c.get("domain") or "")])
                print(f"VERDICT: LOGGED IN -> saved {n} cookies to {path}")
                print(sess.status())
            else:
                print("VERDICT: NOT LOGGED IN - run "
                      "PYTHONPATH=src .venv/Scripts/python.exe -m zameen_mcp.login")
        finally:
            ctx.close()


if __name__ == "__main__":
    main()
