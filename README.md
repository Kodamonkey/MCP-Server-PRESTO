# presto-mcp

A typed, sandboxed [Model Context Protocol](https://modelcontextprotocol.io) server that lets LLMs invoke real **PRESTO** (pulsar / radio-astronomy) tools — `readfile`, `rfifind`, `prepfold` — through Docker. Every invocation is sandboxed (`--network none`, read-only data mount, `--pids-limit`, `no-new-privileges`), persisted to a reproducible run manifest, and exposed as MCP resources.

> PRESTO-only. **Not** PrestoDB, **not** Apache Pulsar, **not** PulsarX / TransientX / riptide / Heimdall / PULSAR_MINER.

---

## What this MVP exposes

| MCP tool                    | What it does                                                              |
|-----------------------------|---------------------------------------------------------------------------|
| `presto.readfile`           | Parse SIGPROC filterbank / PSRFITS header metadata.                       |
| `presto.rfifind`            | Find RFI; produce `.mask`/`.rfi`/`.stats` artifacts.                      |
| `presto.prepfold` (Mode A)  | Fold at a known candidate period + DM. Produces `.pfd` / `.pfd.bestprof`. |
| `presto.list_runs`          | List recent runs from the local `runs/` directory.                        |
| `presto.get_run_manifest`   | Return the full manifest for one `run_id`.                                |

| MCP resource                                          | Contents                              |
|-------------------------------------------------------|---------------------------------------|
| `presto://runs/{run_id}/manifest`                     | `manifest.json` for the run           |
| `presto://runs/{run_id}/stdout`                       | captured PRESTO stdout                |
| `presto://runs/{run_id}/stderr`                       | captured PRESTO stderr                |
| `presto://runs/{run_id}/artifacts/{filename}`         | one artifact (text inline; binary or >1 MiB returns a JSON descriptor) |

---

## Prerequisites

- **Python 3.11+** (3.11 is what `uv sync` provisions by default).
- [**uv**](https://github.com/astral-sh/uv) for environment management. The repo's `pyproject.toml` pins dev tools.
- **Docker Desktop / engine** running on the host.
- PRESTO image pulled:
  ```bash
  docker pull alex88ridolfi/presto5:png
  ```

### Verify Docker + PRESTO

```bash
docker images alex88ridolfi/presto5:png
docker run --rm alex88ridolfi/presto5:png which readfile rfifind prepfold
# Expected: /software/presto5/installation/bin/{readfile,rfifind,prepfold}
```

---

## Install

```bash
uv sync --extra dev
```

This creates `.venv/`, installs `mcp==1.27.1`, Pydantic v2, Typer, dev tools (pytest, ruff).

Copy `.env.example` to `.env` if you want to override defaults:

```bash
cp .env.example .env
```

---

## Run the MCP server (STDIO)

```bash
uv run python -m presto_mcp.server
```

The server reads `PRESTO_*` env vars from `.env` and the environment, ensures `runs/`, `outputs/`, `logs/` exist, runs a startup health check (`docker --version`, non-zero data file sizes), then speaks JSON-RPC on stdio.

### From an MCP client

Copy `examples/mcp/claude_desktop_config.example.json` into your MCP client's config (e.g. Claude Desktop) and update the `cwd` to the absolute repo path:

```json
{
  "mcpServers": {
    "presto": {
      "command": "uv",
      "args": ["run", "python", "-m", "presto_mcp.server"],
      "cwd": "C:/ABSOLUTE/PATH/TO/MCP-Server-Presto"
    }
  }
}
```

### MCP Inspector (recommended for interactive debugging)

```bash
npx @modelcontextprotocol/inspector uv run python -m presto_mcp.server
```

In the Inspector UI:
- `tools/list` should show all five `presto.*` tools.
- Call `presto.readfile` with `{ "input_file": "57762_12049_J0532+3305_000022.fil" }`.
- Call `presto.rfifind` with `{ "input_file": "57762_12049_J0532+3305_000022.fil", "time": 2.0 }`.
- Read `presto://runs/<run_id>/manifest` after either call.

---

## Tests

```bash
# Unit + integration (no Docker required)
uv run pytest -q

# Lint
uv run ruff check .

# End-to-end with real Docker + real data files
uv run pytest -q tests/e2e --run-e2e
```

E2E tests are skipped by default. They invoke the PRESTO image with real data, write real run dirs, and assert the parsed metadata matches expectations from `data/57762_12049_J0532+3305_000022.fil`.

---

## Layout of one run

```
runs/
└── 20260516T143052Z-K7QM3A/
    ├── manifest.json
    ├── stdout.log
    ├── stderr.log
    └── artifacts/
        ├── rfi_rfifind.mask
        ├── rfi_rfifind.rfi
        ├── rfi_rfifind.stats
        ├── rfi_rfifind.ps
        ├── rfi_rfifind.bytemask
        └── rfi_rfifind.inf
```

`run_id` format: `YYYYMMDDTHHMMSSZ-<6-char base32>` (UTC + 30 bits entropy). Lexicographic order is chronological.

The manifest records the full Docker argv, the PRESTO argv, the image (and digest if Docker provides one), CPU/memory caps, timeout, status, exit code, durations, and the list of artifacts.

---

## Security model (summary)

- All inputs go through `presto_mcp.path_security.resolve_input_path`: rejects absolute paths, `..` segments, case-folding tricks, and paths outside `DATA_DIR`.
- All execution uses `subprocess.run(argv, shell=False, timeout=...)`. There is no `shell=True` and no generic `run_command` tool.
- Every Docker invocation runs with `--network none`, `--security-opt no-new-privileges`, `--pids-limit 256`, `--cpus`, `--memory`, a named container, and `--rm`. `data/` mounts read-only.
- Resource URIs revalidate path-traversal at read time. Large/binary artifacts return a JSON descriptor rather than the file body.
- Errors are typed (`PathSecurityError`, `PolicyViolationError`, `DockerInvocationError`, `ParserError`, `ManifestError`); never raw stack traces.

Full design notes in [ARCHITECTURE.md](./ARCHITECTURE.md). Repo conventions for AI coding agents in [CLAUDE.md](./CLAUDE.md) and [AGENTS.md](./AGENTS.md).

---

## Known limits (MVP)

- **Binary PRESTO outputs are not parsed.** `.mask`, `.stats`, `.rfi`, `.pfd` are recorded as artifacts and exposed as resources, but never opened/decoded server-side.
- **`prepfold` Mode A only.** Folding by accel-search candidate file (Mode B) is documented but not implemented — it requires upstream `accelsearch` plumbing which is out of scope.
- **STDIO transport only.** Remote HTTP is deliberately deferred.
- **No SQLite run index.** `presto.list_runs` walks `runs/*/manifest.json`. This is fine for thousands of runs; not for millions.
- **Image is tag-pinned, not digest-pinned at install time.** The manifest captures the digest at runtime if Docker reports it.

## Not in MVP

- PulsarX, TransientX, riptide, Heimdall, PULSAR_MINER, DRAFTS++.
- Workflow tools that chain `rfifind → prepsubband → accelsearch → prepfold`.
- A Python executor or generic shell tool. (And we won't be adding one.)

---

## Project files

- `src/presto_mcp/server.py` — FastMCP entrypoint (the only file that imports FastMCP).
- `src/presto_mcp/docker_backend.py` — argv builder + `subprocess.run` + timeout/kill.
- `src/presto_mcp/path_security.py` — input-path traversal guards.
- `src/presto_mcp/executor.py` — orchestrates one run (paths → backend → parse → manifest).
- `src/presto_mcp/parsers/*` — PRESTO stdout parsers (MVP: stdout only).
- `src/presto_mcp/tools/*` — one module per PRESTO binary.
- `src/presto_mcp/resources.py` — MCP resource handlers.
- `tests/fixtures/stdout/` — captured real PRESTO stdout for contract tests.
- `tests/fakes/fake_docker_backend.py` — in-memory backend honoring `BackendProtocol`.

## License

MIT (see `pyproject.toml`).
