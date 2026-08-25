# Contributing to zameen-mcp

Thanks for helping out. This project is an MCP server for **read-only
research** on Zameen.com — keep that guardrail intact in every change:
no posting, no messaging, no account mutations, nothing sent to anyone.

## Ground rules

- **Public repo.** No secrets, API keys, passwords, or personal names,
  paths, emails, or phone numbers in any committed file, test, fixture, or
  log line.
- **Never commit** `fixtures/`, `data/`, `session_state.json`, `.venv/`,
  or anything gitignored. Captured Zameen pages contain third-party PII;
  fixtures stay local by design (`.gitignore` already excludes them — don't
  fight it).
- Read-only guardrails are contractual: client code issues GET requests
  only, and tools that touch "messaging" must remain draft-only.

## Development setup

Python **3.11+** required.

```bash
git clone https://github.com/lonewolfmasanaga/zameen.com-mcp
cd zameen.com-mcp
python -m venv .venv

# Windows:
.venv\Scripts\python.exe -m pip install -e ".[dev]"
# macOS/Linux:
.venv/bin/python -m pip install -e ".[dev]"

# run the offline test suite
.venv\Scripts\python.exe -m pytest -q        # Windows
.venv/bin/python -m pytest -q                # macOS/Linux
```

`[dev]` installs pytest and playwright; the Playwright browser binary is only
needed if you exercise the optional login flow locally (`python -m playwright
install chromium`).

### Project layout

| Path | What it is |
|---|---|
| `src/zameen_mcp/server.py` | FastMCP server: the 9 tool definitions + JSON responses |
| `src/zameen_mcp/client.py` | URL building + read-only HTTP GETs (requests) |
| `src/zameen_mcp/parsers.py` | Pure HTML → data extraction (BeautifulSoup/lxml), no network |
| `src/zameen_mcp/models.py` | `Listing` / `SearchResult` dataclasses (field contract) |
| `src/zameen_mcp/session.py` | Optional cookie session storage + login window |
| `src/zameen_mcp/login.py` | `python -m zameen_mcp.login` interactive flow |
| `src/zameen_mcp/watchlist.py` | Local watchlist store under `$ZAMEEN_MCP_HOME` |
| `tests/` | Offline pytest suite |
| `fixtures/` | **Local-only** captured pages (gitignored); tests skip without them |

## Branch naming

Branch off the latest `main`. Use `<type>/<short-topic>`:

```
feat/<topic>       # new capability      e.g. feat/core-hardening
fix/<topic>        # bug fix             e.g. fix/network-hardening
docs/<topic>       # documentation only  e.g. docs/user-guide
chore/<topic>      # tooling/release     e.g. chore/release-engineering
ci/<topic>         # CI/workflows        e.g. ci/github-actions
```

**Never commit directly to `main`.** Keep each branch scoped to one topic and
only touch files that topic needs; if your change requires edits in files you
don't own (e.g. `README.md`, `pyproject.toml`), open an issue / note it in
your PR description instead of editing them.

## Test rules

1. **All tests run offline.** No network access in unit tests, ever. Stub or
   monkeypatch the HTTP layer instead of hitting zameen.com — see
   `tests/conftest.py` for the existing pattern (a stub `client` module is
   injected when needed, and an autouse fixture forces the anonymous session
   so real cookies on disk can never leak into tests).
2. **Fixtures are local-only.** `tests/test_parsers.py` and friends run
   against captured pages in `fixtures/`; those files are gitignored because
   they contain third-party PII. Tests skip gracefully when fixtures are
   absent — a green suite with skips is correct behavior, not something to
   fix by committing captures.
3. **Every added test must pass offline**: `.venv/Scripts/python.exe -m
   pytest -q` fully green before you push.
4. Prefer table-driven tests with inline HTML strings for parser edge cases;
   they document behavior and stay hermetic.

`smoke_test.py` at the repo root is a **live**, networked end-to-end check.
Run it manually when debugging against reality — it is not part of the test
suite and must not be invoked from CI or from other tests.

## Pull-request flow

1. Fork or branch from latest `main` using the naming scheme above.
2. Make small, focused commits; keep formatting changes out of functional PRs.
3. Ensure the offline suite is green: `python -m pytest -q`.
4. Push your branch and open a PR against `main` describing what changed and
   why. Include test names for any new tests.
5. CI runs the suite across Python 3.11/3.12 on Ubuntu and Windows — keep it
   green (Windows compatibility matters: this project's own docs use
   `.venv\Scripts\python.exe` paths).
6. A maintainer reviews and merges. Squash or rebase-merge; avoid merge
   commits. If multiple workstreams land in parallel, coordinate merge order
   so later branches rebase cleanly.

## Code style

- Type-hint all public functions; docstrings explain *why* where non-obvious.
- Server tools return pretty-printed JSON and catch their own exceptions into
  `{"error": ...}` bodies (see [docs/TOOLS.md](docs/TOOLS.md) → Error shapes)
  rather than raising across the wire.
- Heavyweight sibling modules import lazily inside tool bodies so
  `server.py` stays importable while modules evolve.
- Parsers stay pure functions: HTML in, data out, None-safe on missing fields.

## Versioning & releases

Version lives solely in `src/zameen_mcp/__init__.py`
(`__version__`); changelog entries follow [Keep a Changelog](CHANGELOG.md).
See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) §5 for the release checklist.
