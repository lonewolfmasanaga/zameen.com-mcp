<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)"
          srcset="https://raw.githubusercontent.com/lonewolfmasanaga/zameen.com-mcp/main/assets/zameen-logo-white.svg">
  <img src="https://raw.githubusercontent.com/lonewolfmasanaga/zameen.com-mcp/main/assets/zameen-logo.png"
       alt="zameen.com" width="360">
</picture>

### MCP server for researching property listings on Zameen.com

[![License: MIT](https://img.shields.io/badge/License-MIT-00A551.svg)](LICENSE)
[![CI](https://github.com/lonewolfmasanaga/zameen.com-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/lonewolfmasanaga/zameen.com-mcp/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB.svg)](https://www.python.org)
[![MCP](https://img.shields.io/badge/Protocol-MCP-7C3AED.svg)](https://modelcontextprotocol.io)

**Verified / Titanium-agent filtering · local watchlists · listing details ·
agent-message drafting — through 9 structured tools in any MCP client.**

[Tool reference](docs/TOOLS.md) · [Deployment guide](docs/DEPLOYMENT.md) ·
[Contributing](CONTRIBUTING.md) · [Changelog](CHANGELOG.md)

</div>

---

An MCP (Model Context Protocol) server for researching property listings on
[Zameen.com](https://www.zameen.com) — Pakistan's largest real estate portal —
through structured tools instead of fragile screen scraping.

> **Trademark notice:** "Zameen" and the Zameen.com logo are trademarks of
> Zameen.com (EMPG). They are used here solely to identify the service this
> tool interfaces with. This project is unaffiliated with, and not endorsed
> by, Zameen.com.

Works with any MCP client: Claude Desktop, Hermes Agent, Cursor, and others.

## Install

```bash
# run directly with no permanent install (recommended)
uvx zameen-mcp

# or install as an isolated CLI tool
pipx install zameen-mcp
```

### Register in your MCP client

```json
{
  "mcpServers": {
    "zameen": {
      "command": "uvx",
      "args": ["zameen-mcp"]
    }
  }
}
```

That's it — 9 tools appear in your AI client.

## Tools

| Tool | What it does |
|---|---|
| `search_properties` | Structured search: city, purpose, type, beds, price, area, keywords, sort |
| `get_listing_details` | Full detail page for one listing (URL or numeric id) |
| `list_supported_cities` | Verified city slugs + property types |
| `add_watch` / `check_watch` | Save search criteria locally; later re-checks report only NEW listings |
| `list_watches` / `remove_watch` | Manage saved watches |
| `draft_agent_message` | Compose a polite inquiry for a listing — **draft only, never sends** |
| `account_status` | Whether an authenticated session is loaded |

Badge-level filtering Zameen's own UI can't do: `verified_only`,
`agent_tier` (e.g. `"titanium"`), `exclude_promoted`.

Full parameter reference + natural-language cheat sheet: [docs/TOOLS.md](docs/TOOLS.md)

## Optional: log in to your Zameen account

Anonymous searching works out of the box. To also ride **your** logged-in
session (saved searches, personalized pages):

```bash
pipx inject zameen-mcp playwright && .venv/bin/playwright install chromium   # pipx
uv tool install zameen-mcp --with playwright && playwright install chromium  # uv

zameen-mcp-login   # opens a Chromium window; YOU log in; cookies stay local
```

Your password is never seen or stored by this software — only the resulting
session cookies, kept in `~/.zameen-mcp/` on **your** machine. Wipe anytime:
`zameen-mcp-login --logout`.

## Data location

All state lives in `~/.zameen-mcp/` (`watches.json`, `session_state.json`,
`chrome-profile/`). Override with the `ZAMEEN_MCP_HOME` environment variable.
Treat `session_state.json` like a password: it grants access to your account
while valid.

## Development

```bash
git clone <repo-url> && cd zameen.com
uv venv .venv && uv pip install -p .venv/Scripts/python.exe -e ".[dev]"
.venv/Scripts/python.exe -m pytest -q          # offline suite against real captured pages
.venv/Scripts/python.exe smoke_test.py         # live end-to-end check
```

## Compliance & fair use

- Zameen.com's `robots.txt` disallows crawling its major-city listing pages.
  This server is built for **interactive, human-paced research** — a person
  asking their assistant questions — not bulk harvesting or redistribution.
- Requests go out one at a time with browser-like headers. Don't remove the
  pacing or loop searches unattended.
- Listing data belongs to Zameen.com and its advertisers; "Zameen" is a
  trademark of Zameen.com. This project is unaffiliated and not endorsed.
- Prices are agent-entered, as-listed — not verified market valuations.

## Limitations

- Read-only by design: no posting, messaging, or account changes — contacting
  agents is deliberately a human action (`draft_agent_message` only drafts).
- Badge filters operate on fetched result pages (up to 3 per call).
- Parsing targets Zameen's current HTML; site redesigns may require parser
  updates (fixtures make regressions easy to catch).

MIT licensed — see [LICENSE](LICENSE).
