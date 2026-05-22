# AGENTS.md

Portable instructions for any coding agent working in this repo.

## Project purpose

Typed, sandboxed MCP server that exposes **PRESTO** (radio-astronomy / pulsar) routines to LLMs through a sandboxed Docker executor. PRESTO-only — not PrestoDB, Apache Pulsar, PulsarX, TransientX, riptide, Heimdall, or PULSAR_MINER.

The server registers **45** `presto.*` tools (profile-gated via `PRESTO_TOOL_PROFILE`) — 38 PRESTO/utility tools plus 7 modern-reporting tools — alongside MCP resources and prompts. See [README.md](./README.md) for the full tool table and [TOOLS.md](./docs/TOOLS.md) for utility-tool details.

## Stack

- Python 3.11+
- FastMCP (`mcp` SDK, pinned exact version in `pyproject.toml`)
- Pydantic v2
- pytest, ruff
- `uv` for environment + dep management
- Docker CLI (host) — image `alex88ridolfi/presto5:png`

## Hard rules

1. **No `shell=True`.** Build argv as a Python list. Invoke via `subprocess.run(argv, shell=False, timeout=…)`.
2. **No generic-shell MCP tool.** No `run_command`, `exec`, etc. One typed tool per PRESTO binary.
3. **All paths via `path_security`.** Reject absolute paths, `..`, paths outside `DATA_DIR`. Outputs only inside the run-dir or configured `outputs/`.
4. **All execution inside Docker.** Never call PRESTO binaries on the host. Always with `--network none`, `--security-opt no-new-privileges`, `--pids-limit 256`, `--cpus`, `--memory`, `:readonly` bind for `data/`.
5. **Every run writes a manifest.** Even when the tool fails or times out. Includes `docker_argv`, `presto_argv`, `exit_code`, `status`, durations, artifact list.
6. **Every tool returns structured output.** `ToolRunResult[T]` Pydantic model. MCP resource URIs for manifest/stdout/stderr/artifacts.
7. **Errors are typed.** `PathSecurityError`, `DockerInvocationError`, `ParserError`, `PolicyViolationError` → MCP error payloads. Never leak raw stack traces.
8. **No LangGraph (or other orchestration framework) inside this MCP server.** Stateful / adaptive workflows belong to a separate layer above this MCP.
9. **MCP prompts are guidance, not pipelines.** A prompt returns text telling the client which tools to call. It must not invoke any tool, read a file, or call Docker.
10. **Utility tools never execute arbitrary shell.** Tools like `presto.list_data_files`, `presto.validate_environment`, `presto.summarize_run`, `presto.inspect_artifacts` may stat the filesystem and (only for `validate_environment`) probe `docker --version` / `docker image inspect` via `subprocess.run(argv, shell=False, timeout=…)`.
11. **Do not duplicate existing PRESTO tools.** Each PRESTO binary already has one typed wrapper under `src/presto_mcp/tools/`. New work extends utility/navigation/prompt surfaces, not the PRESTO surface.
12. **Prefer curated, typed wrappers to indiscriminate PRESTO coverage.** Not every PRESTO routine deserves an MCP tool — pick ones with clear inputs/outputs, validate them, and ship tests.
13. **New routines must be verified against the configured Docker image before being marked `stable`.** Default to `[experimental]` (or `[advanced]`) in the `@mcp.tool` description until an E2E smoke (or `presto.validate_environment`) confirms availability in `alex88ridolfi/presto5:png` (or the configured successor).

## Layout

```
src/presto_mcp/
  server.py            # FastMCP app — only file that imports FastMCP
  server_tools.py      # @mcp.tool registration (45 tools)
  server_resources.py  # MCP resources
  server_prompts.py    # MCP prompts
  config.py            # env-driven settings, startup health check
  executor.py          # paths → backend → parse → manifest
  docker_backend.py    # argv builder + subprocess.run + timeout/kill
  path_security.py     # resolve_input_path, create_run_dir, new_run_id
  policies.py          # numeric guards
  parsers/             # stdout-only PRESTO parsers
  tools/               # one run_<name>() per tool (+ reporting.py)
  reporting/           # modern artifact/report layer → outputs/<run_id>/
  observability/       # structured logging + RunTracker → logs/
  bin/                 # waterfaller_headless.py (copied into run dir)
tests/
  unit/ integration/ e2e/
  fakes/fake_docker_backend.py
  fixtures/stdout/
```

## Run-ID

`YYYYMMDDTHHMMSSZ-<6char base32>` — UTC timestamp + entropy. Stdlib only. Filesystem-safe on Windows.

## Resource URIs

- `presto://runs/{run_id}/manifest` → `runs/<id>/manifest.json`
- `presto://runs/{run_id}/stdout` → `runs/<id>/stdout.log`
- `presto://runs/{run_id}/stderr` → `runs/<id>/stderr.log`
- `presto://runs/{run_id}/artifacts/{filename}` → `runs/<id>/artifacts/<filename>`

## Docker baseline (every PRESTO invocation)

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

`data/` mounts read-only. Run dir mounts read-write at `/outputs`. Use `--mount type=bind,...` (loud failure) not `-v`.

## What NOT to touch

- `data/` — real telescope observations. Never write. Never delete.
- `docker.sock` — do not mount it anywhere.
- Don't add PulsarX, TransientX, riptide, Heimdall, PULSAR_MINER, or DRAFTS++ here.
- Don't add HTTP transport in this repo; stdio only.

## OneDrive caveat

Repo may live under `C:\Users\...\OneDrive\...`. OneDrive can turn data files into 0-byte cloud placeholders. `config.py` startup check rejects 0-byte files. Fix: Explorer → right-click `data/` → "Always keep on this device".

## Setup

```bash
uv sync --extra dev
```

## Develop

```bash
ruff check .
pytest -q                          # unit + integration
pytest -q tests/e2e --run-e2e      # E2E with Docker (+ real data where applicable)
uv run python -m presto_mcp.server # boot MCP server (stdio)
```

## Definition of done (per tool)

1. Typed function under `src/presto_mcp/tools/<name>.py` (`async run_<name>(...) -> ToolRunResult[T]`).
2. Registered in `server_tools.py`.
3. Unit test (parser / input validation) + integration test (`FakeDockerBackend`).
4. `@pytest.mark.e2e` smoke where feasible (skipped unless `--run-e2e`).
5. Manifest with `docker_argv`, `presto_argv`, `exit_code`, `status`, artifact list.
6. Docs in `docs/TOOLS.md` / `README.md` / `docs/RUNTIME_COMPATIBILITY.md` as appropriate.

## Validate (acceptance)

- `pytest -q` green.
- `uv run python -m presto_mcp.server` boots without error.
- `presto.validate_environment` reports Docker + image readiness.
- `presto.readfile` on `57762_12049_J0532+3305_000022.fil` → `central_freq_mhz ≈ 1564.25`, `num_channels == 672`.
- Every invocation writes `runs/<id>/manifest.json` + stdout/stderr logs.

## Where to look

- `src/presto_mcp/docker_backend.py` — security-critical argv + subprocess.
- `src/presto_mcp/path_security.py` — traversal guards.
- `src/presto_mcp/executor.py` — single-run orchestration.
- `src/presto_mcp/server_tools.py` — tool registration + profiles.
- `src/presto_mcp/tool_metadata.py` — `PRESTO_TOOL_PROFILE` contract.
- `src/presto_mcp/runtime_checks.py` — image readiness probes.
- `tests/fakes/fake_docker_backend.py` — test double for Docker.

## Style

- Pydantic v2 models for all schemas.
- Async at the MCP edge; blocking subprocess in `asyncio.to_thread`.
- Pin FastMCP to an exact version in `pyproject.toml`.
- Ruff defaults; no extra formatters.
