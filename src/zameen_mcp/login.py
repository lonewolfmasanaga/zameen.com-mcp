"""One-time interactive login for zameen-mcp.

Run from the project root::

    PYTHONPATH=src .venv/Scripts/python.exe -m zameen_mcp.login          # log in
    PYTHONPATH=src .venv/Scripts/python.exe -m zameen_mcp.login --logout # wipe

A Chromium window opens at zameen.com/login; YOU type your credentials there.
This program only saves the resulting session cookies afterwards — the
password is never seen or stored by any code in this project.
"""

from __future__ import annotations

import sys

from .session import SESSION_FILE, clear, open_login_window


def main() -> None:
    if "--logout" in sys.argv:
        removed = clear()
        print("Session cleared." if removed else "No saved session found.")
        return

    print("=" * 62)
    print(" A Chromium window will open at zameen.com/login.")
    print(" Log in YOURSELF - this program never sees your password.")
    print(" The session is saved AUTOMATICALLY once you land past")
    print(" the login page. Keep this window running until then.")
    print("=" * 62)
    n = open_login_window()
    if n:
        print(f"\nSaved {n} cookies -> {SESSION_FILE}")
        print("Restart any running MCP server sessions to pick these up.")
    else:
        print("\nNothing saved (window closed or timed out).")


if __name__ == "__main__":
    main()
