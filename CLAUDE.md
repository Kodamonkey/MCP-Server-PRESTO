# PRESTO MCP — instructions for Claude Code

## Project purpose
Typed, sandboxed MCP server that exposes **PRESTO** (pulsar / radio-astronomy) routines to LLMs via Docker. PRESTO-only. Not PrestoDB. Not Apache Pulsar. Not PulsarX. Not TransientX. Not riptide. Not Heimdall. Not PULSAR_MINER.

## Non-negotiable rules

- **No shell.** `subprocess.run(..., shell=False)`. Build Docker argv as a Python list. Never `bash -lc`, never `os.system`.
- **No generic executor.** Don't add a tool called `run_command`, `exec`, `python_exec`, etc. Each PRESTO binary gets its own typed tool.
- **No arbitrary paths.** All input paths from the model/user go through `path_security.resolve_input_path` (must resolve inside `DATA_DIR`). Outputs only inside `runs/<run_id>/artifacts/` or `outputs/`.
- **No host execution.** PRESTO never runs on the host. Always inside `alex88ridolfi/presto5:png` (or a pinned successor).
- **No new backends in MVP.** No PulsarX, TransientX, riptide, Heimdall, PULSAR_MINER, DRAFTS++, HTTP transport. Stdio only.
- **No `docker.sock` mounting.** This server invokes the host's `docker` CLI; it does not run inside another container.
- **Every invocation writes `runs/<run_id>/manifest.json`** — even on failure / timeout. `stdout.log` and `stderr.log` are always persisted.
- **Every MCP tool returns `structuredContent`.** Plus a brief human string. Plus MCP resource URIs for manifest/stdout/stderr/artifacts.
- **Controlled errors.** Surface `PathSecurityError`, `DockerInvocationError`, `ParserError`, `PolicyViolationError` as MCP error payloads — not raw stack traces.

## Stack

- Python 3.11+
- `mcp` / FastMCP (pinned exact version)
- Pydantic v2
- Typer (optional CLI)
- pytest, ruff
- Docker CLI (host)

## Layout

```
src/presto_mcp/
  server.py           # FastMCP app, only file that imports FastMCP
  config.py           # env-driven settings, startup health check
  errors.py
  models.py           # Pydantic schemas
  policies.py         # cpu/mem/time caps
  path_security.py    # resolve_input_path, create_run_dir, ensure_inside_root
  docker_backend.py   # argv builder + subprocess.run + timeout/kill
  executor.py         # orchestrate: paths → backend → parse → manifest
  manifest.py         # write/load/list manifests
  resources.py        # MCP resource handlers
  parsers/            # readfile_parser, rfifind_parser (stdout only, MVP)
  tools/              # readfile, rfifind, prepfold, list_runs (plain async functions)
tests/
  conftest.py         # --run-e2e flag, fixtures
  fakes/              # FakeDockerBackend
  fixtures/stdout/    # captured real PRESTO stdout
  unit/  integration/  e2e/
```

## Run-ID

`YYYYMMDDTHHMMSSZ-<6char base32>` — UTC timestamp + entropy. Stdlib only. Filesystem-safe on Windows. Sorts chronologically.

## Resource URIs

- `presto://runs/{run_id}/manifest` → `runs/<id>/manifest.json`
- `presto://runs/{run_id}/stdout`   → `runs/<id>/stdout.log`
- `presto://runs/{run_id}/stderr`   → `runs/<id>/stderr.log`
- `presto://runs/{run_id}/artifacts/{filename}` → `runs/<id>/artifacts/<filename>` (large files return metadata only)

## Docker baseline (must appear in every invocation)

```
docker run --rm --name presto-<run_id>
  --network none
  --cpus <PRESTO_DEFAULT_CPUS>
  --memory <PRESTO_DEFAULT_MEMORY_MB>m
  --pids-limit 256
  --security-opt no-new-privileges
  --stop-timeout 5
  --mount type=bind,src=<DATA_DIR_ABS>,dst=/data,readonly
  --mount type=bind,src=<RUN_DIR_ABS>,dst=/outputs
  alex88ridolfi/presto5:png
  <presto-binary> <args...>
```

`data/` mounts read-only. Run dir mounts read-write at `/outputs`. Use `--mount type=bind,...` (loud failure) not `-v` (silent empty bind).

## Commands

```
# Install
uv sync --extra dev

# Lint
ruff check .

# Unit + integration
pytest -q

# E2E (requires Docker + real data)
pytest -q tests/e2e --run-e2e

# Start MCP server (STDIO)
uv run python -m presto_mcp.server

# Inspector (Node required)
npx @modelcontextprotocol/inspector uv run python -m presto_mcp.server
```

## Definition of done (per tool)

1. Typed function under `src/presto_mcp/tools/<name>.py` (`async run_<name>(...) -> ToolRunResult[T]`).
2. `@mcp.tool` registered in `server.py`.
3. Unit test (pure-function: parser, input validation).
4. At least one integration test using `FakeDockerBackend`.
5. At least one `@pytest.mark.e2e` test invoking real Docker on real `data/` file (skipped unless `--run-e2e`).
6. Manifest written with full `docker_argv`, `presto_argv`, `exit_code`, `status`, durations, artifact list.
7. Result includes `run_id`, `status`, `manifest_uri`, `stdout_uri`, `stderr_uri`, `artifact_uris[]`.

## What NOT to touch

- `data/` — real observation files. Never delete, never write. Mount `:readonly` always.
- `Claude.md` is gone; this file is `CLAUDE.md` (uppercase, standard).
- Existing research markdown (`DeepResearch-MCPServer.md`, `deep-research-report.md`) — reference material, do not modify.

## OneDrive caveat

Repo is under `C:\Users\sebas\OneDrive\...`. OneDrive may turn data files into 0-byte cloud placeholders. `config.py` startup check rejects 0-byte files. Fix: Explorer → right-click `data/` → "Always keep on this device".
