# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.0] - 2026-08-25

### Added
- Official Zameen logo assets (light/dark adaptive) and README header with badges and trademark notice.
- GitHub Actions CI workflow running the test suite on Python 3.11/3.12 (Ubuntu + Windows), plus weekly Dependabot updates for pip and GitHub Actions dependencies.
- Network hardening in `zameen_mcp.client`: configurable HTTP retries with backoff (`configure_http`) and a politeness delay between requests to zameen.com (`set_politeness`); authenticated-session behavior unchanged.
- Core hardening in `zameen_mcp.server` / `zameen_mcp.parsers`: search `limit` clamped to a valid range, JSON error shapes guaranteed for every tool, and defensive parser fixes (empty/None HTML, cards missing fields, malformed prices, areas without numbers, duplicate listing ids across pages).
- User documentation: `docs/TOOLS.md` (tool reference synced to server signatures, with error shapes), `docs/DEPLOYMENT.md` (uvx/pipx usage, Hermes and Claude Desktop configuration, login flow, PyPI publish checklist), and `CONTRIBUTING.md`.
- Release engineering: `.github/workflows/release.yml` building sdist/wheel on `v*` tags, publishing to PyPI via Trusted Publishing (OIDC — no token secret), and attaching artifacts to a GitHub Release; this changelog added.

## [0.2.0] - 2026-08-25

### Added
- MCP server (`zameen-mcp`) for researching property listings on Zameen.com: 9 tools covering structured search with badge-level filters (verified/titanium/promoted), listing details, local watchlists, agent-message drafting (draft-only, never sends messages), and an optional authenticated session.
- FastMCP stdio server built on `requests` + BeautifulSoup parsers — no browser needed for normal operation.
- Per-user state stored in `~/.zameen-mcp`; one-time browser login flow via the `zameen-mcp-login` entry point.
- 68 offline tests written against real captured pages.
- Project packaging (hatchling), README, license, and initial documentation.

## [0.1.0]

Initial internal prototype of the MCP server, developed before this
repository's git history began; specific changes were not recorded.

[Unreleased]: https://github.com/lonewolfmasanaga/zameen.com-mcp/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/lonewolfmasanaga/zameen.com-mcp/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/lonewolfmasanaga/zameen.com-mcp/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/lonewolfmasanaga/zameen.com-mcp/releases/tag/v0.1.0
