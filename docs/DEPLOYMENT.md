# Deployment Guide — zameen-mcp

How to run the `zameen` MCP server and point MCP clients at it. Tool
behaviour is documented separately in [docs/TOOLS.md](TOOLS.md).

**Requirements:** Python 3.11 or 3.12, any OS (Windows / macOS / Linux).
The server speaks MCP over **stdio** — it has no ports, no daemon, and no
network listener; your MCP client launches and manages its lifetime.

---

## 1. Run without a permanent install

```bash
# run directly, cached by uv (recommended)
uvx zameen-mcp

# or install as an isolated CLI tool
pipx install zameen-mcp
```

Both expose the same entry points:

- `zameen-mcp` — the MCP server (`zameen_mcp.server:main`)
- `zameen-mcp-login` — the optional one-time login helper (see §4)

### From source instead

```bash
git clone https://github.com/lonewolfmasanaga/zameen.com-mcp
cd zameen.com-mcp
python -m venv .venv
# Windows: .venv\Scripts\python.exe -m pip install -e .
# macOS/Linux:
.venv/bin/python -m pip install -e .
.venv/bin/python -m zameen_mcp.server   # run the server over stdio
```

---

## 2. Register with your MCP client

All clients take the same JSON shape. Pick the variant matching how you run
the server:

```jsonc
// uvx (no permanent install)
{ "mcpServers": { "zameen": { "command": "uvx", "args": ["zameen-mcp"] } } }

// pipx
{ "mcpServers": { "zameen": { "command": "pipx", "args": ["run", "zameen-mcp"] } } }

// from source — use an absolute path to the venv python
{ "mcpServers": { "zameen": {
      "command": "/absolute/path/to/.venv/bin/python",   // Windows: .venv\\Scripts\\python.exe
      "args": ["-m", "zameen_mcp.server"] } } }
```

On Windows, `uvx`/`pipx` resolve to `uvx.exe`/`pipx.exe`; if your client can't
find them, give the absolute path to the executable in `"command"`.

### Claude Desktop

Edit the config file (create it if missing), then fully quit and restart
Claude Desktop:

| OS | Path |
|---|---|
| Windows | `%APPDATA%\Claude\claude_desktop_config.json` |
| macOS | `~/Library/Application Support/Claude/claude_desktop_config.json` |

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

After restart, the 9 tools appear under the "zameen" server entry.

### Hermes Agent

```bash
hermes mcp add zameen --command uvx --args zameen-mcp
hermes mcp test zameen     # verify connection + tool discovery
```

To pass environment variables (e.g. `ZAMEEN_MCP_HOME`, see §3):

```bash
hermes mcp add zameen --command uvx --args zameen-mcp \
  --env ZAMEEN_MCP_HOME=/path/to/zameen-data
```

### Other clients (Cursor, etc.)

Any client that supports stdio MCP servers uses the same `mcpServers` JSON as
above in its own config location — consult the client's docs for where.

---

## 3. Data location & `ZAMEEN_MCP_HOME`

All persistent state lives in one per-user directory:

| Contents of `$ZAMEEN_MCP_HOME` (default: `~/.zameen-mcp`) | What it is |
|---|---|
| `watches.json` | local watchlists created by `add_watch` |
| `session_state.json` | saved Zameen session cookies (only if you used the login flow) |
| `chrome-profile/` | persistent Chromium profile used by the login window |

Override the directory with the `ZAMEEN_MCP_HOME` environment variable — set
it globally, or per-client via the client's `env` config block:

```json
{ "mcpServers": { "zameen": {
      "command": "uvx", "args": ["zameen-mcp"],
      "env": { "ZAMEEN_MCP_HOME": "D:/data/zameen-mcp" } } } }
```

> Treat `session_state.json` like a password: while valid it grants access to
> your Zameen account. It is never committed to this repo (`data/`,
> `session_state.json` are gitignored) and never leaves your machine except
> as cookies riding requests to zameen.com itself.

---

## 4. Optional: log in to your Zameen account

Anonymous searching works out of the box. The login flow is only for riding
**your** logged-in session (saved searches, personalized pages). It is a
one-time interactive step — the user logs in personally; no code in this
project ever sees or stores a password.

**Install the browser extra** (Playwright + Chromium):

```bash
pipx inject zameen-mcp playwright && playwright install chromium   # pipx
uv tool install zameen-mcp --with playwright && playwright install chromium  # uv
# from source: .venv/Scripts/python.exe -m playwright install chromium
```

**Log in:**

```bash
zameen-mcp-login            # or: python -m zameen_mcp.login
```

A Chromium window opens at zameen.com/login. Log in yourself; once Zameen's
own page confirms the session, cookies are saved automatically to
`$ZAMEEN_MCP_HOME/session_state.json` (default wait: 30 minutes; closing the
window loses nothing — the profile persists, just re-run).

**Restart any running MCP sessions** so the server picks the cookies up at
startup (auth is bootstrapped when the server starts, silently falling back
to anonymous if none/expired).

**Verify:** call the `account_status` tool →

```json
{ "logged_in": true, "cookie_count": 14, "saved_at": "2026-08-25T10:00:00" }
```

If `logged_in` comes back `false`, the cookies expired — re-run
`zameen-mcp-login`.

**Log out / wipe:**

```bash
zameen-mcp-login --logout   # or delete $ZAMEEN_MCP_HOME/session_state.json
```

---

## 5. PyPI publish checklist (maintainers)

The version single-source-of-truth is `__version__` in
`src/zameen_mcp/__init__.py` (hatchling reads it via
`[tool.hatch.version]`). Do **not** duplicate versions elsewhere.

Current flow (API token):

1. ☐ Bump `__version__` in `src/zameen_mcp/__init__.py`; add a CHANGELOG entry.
2. ☐ Clean old artifacts: delete `dist/`.
3. ☐ Build sdist + wheel: `python -m build` (or `uv build`).
4. ☐ Sanity-check metadata: `twine check dist/*`.
5. ☐ Test upload: `twine upload --repository testpypi dist/*`; install from
   TestPyPI into a scratch venv and confirm `uvx --index-url
   https://test.pypi.org/simple/ zameen-mcp` starts.
6. ☐ Upload: `twine upload dist/*`.
7. ☐ Tag `v<version>` on the release commit; create the GitHub Release and
   attach the `dist/` artifacts.

Future option — **Trusted Publishing** (no API token secret):

- A GitHub Actions workflow triggered on tag push `v*` that builds with
  `python -m build`, then publishes with `pypa/gh-action-pypi-publish`
  using OIDC: job-level `permissions: id-token: write`, no `PYPI_API_TOKEN`
  secret required.
- Register the repo once under PyPI → project settings → *Trusted
  Publishing* (workflow filename + environment must match).
- Until that workflow lands, keep the twine path above as the source of
  truth; don't maintain both simultaneously for the same release.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| Tools don't appear in the client | Fully restart the client (Claude Desktop especially); check `command` resolves on PATH (use absolute paths on Windows) |
| `ModuleNotFoundError: fastmcp` | Install with extras included (`pip install -e .` from source) or use `uvx`/`pipx` which resolve deps automatically |
| Login step fails: "playwright is not installed" | Install the extra + Chromium browser (§4); plain searches don't need Playwright |
| `account_status` says `logged_in: false` after logging in | Server was already running — restart the MCP session so auth bootstraps; else cookies expired, re-run `zameen-mcp-login` |
| Watches vanished | You changed `ZAMEEN_MCP_HOME` between runs; watches live inside that directory |
