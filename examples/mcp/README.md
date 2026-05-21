# MCP client templates

Templates for Cursor and Claude Desktop. **The canonical installation guide is in the [repo README](../../README.md#installation-canonical).**

## What to replace

Only one placeholder appears in these JSON files:

| Placeholder | Value |
|-------------|--------|
| `REPLACE_WITH_REPO_ROOT` | **Absolute** path to your clone (no trailing slash) |

Ejemplo Windows: `C:\\Users\\alice\\projects\\MCP-Server-Presto`

Do not add an `"env"` block to JSON: all configuration belongs in `.env` at the repo root (see README).

## Files

| File | Destination |
|---------|---------|
| `cursor_mcp.example.json` | `.cursor/mcp.json` in the repo root (or merge into global Cursor config) |
| `claude_desktop_config.example.json` | `presto` block inside system `claude_desktop_config.json` |

Claude Desktop config paths:

- **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`
- **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`

Fully restart the app after editing JSON.

**Common error:** placing `"presto": { ... }` at the same level as `"mcpServers"`. Claude **only** reads servers **inside** `"mcpServers": { "presto": { ... } }`. If `mcpServers` is `{}`, nothing starts.

## If `uv` is not on client PATH

Replace `"command": "uv"` with the absolute path to the binary, e.g. `C:\\Users\\alice\\.local\\bin\\uv.exe` (Windows).

## Alternative: venv Python

After `uv sync`, you can use the venv interpreter instead of `uv run`:

| OS | `command` |
|----|-----------|
| Windows | `<REPO>\\.venv\\Scripts\\python.exe` |
| macOS/Linux | `<REPO>/.venv/bin/python` |

`args`: `["-m", "presto_mcp.server"]` - keep `PRESTO_*` only in `.env`.
