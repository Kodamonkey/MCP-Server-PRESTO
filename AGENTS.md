# AGENTS.md

Portable instructions for any coding agent working in this repo.

## Project purpose

Typed MCP server that exposes **PRESTO** (radio-astronomy / pulsar) routines to LLMs through a sandboxed Docker executor. PRESTO-only. The MVP wraps three binaries — `readfile`, `rfifind`, `prepfold` — plus two reflection tools (`list_runs`, `get_run_manifest`).

## Stack

- Python 3.11+
- FastMCP (official MCP Python SDK), Pydantic v2
- Docker CLI (host) — image `alex88ridolfi/presto5:png`
- pytest, ruff
- `uv` for environment + dep management

## Hard rules

1. **No `shell=True`.** Build argv as a Python list. Invoke via `subprocess.run(argv, shell=False, timeout=…)`.
2. **No generic-shell MCP tool.** No `run_command`, `exec`, etc. One typed tool per PRESTO binary.
3. **All paths via `path_security`.** Reject absolute paths, `..`, paths outside `DATA_DIR`. Outputs only inside the run-dir or configured `outputs/`.
4. **All execution inside Docker.** Never call PRESTO binaries on the host. Always with `--network none`, `--security-opt no-new-privileges`, `--pids-limit 256`, `--cpus`, `--memory`, `:readonly` bind for `data/`.
5. **Every run writes a manifest.** Even when the tool fails or times out. Includes `docker_argv`, `presto_argv`, `exit_code`, `status`, durations, artifact list.
6. **Every tool returns structured output.** `ToolRunResult[T]` Pydantic model. MCP resource URIs for manifest/stdout/stderr/artifacts.
7. **Errors are typed.** `PathSecurityError`, `DockerInvocationError`, `ParserError`, `PolicyViolationError` → MCP error payloads. Never leak raw stack traces.
8. **No LangGraph (or other orchestration framework) inside this MCP server.** Stateful / adaptive workflows belong to a separate layer above this MCP. The server only ships atomic capabilities, navigable state, and guidance prompts.
9. **MCP prompts are guidance, not pipelines.** A prompt returns text telling the client which tools to call. It must not invoke any tool, read a file, or call Docker.
10. **Utility tools never execute arbitrary shell.** Tools like `presto.list_data_files`, `presto.validate_environment`, `presto.summarize_run`, `presto.inspect_artifacts` may stat the filesystem and (only for `validate_environment`) probe `docker --version` / `docker image inspect` via `subprocess.run(argv, shell=False, timeout=…)`. Nothing else.
11. **Do not duplicate existing PRESTO tools.** Each PRESTO binary already has one typed wrapper under `src/presto_mcp/tools/`. New work extends utility/navigation/prompt surfaces, not the PRESTO surface.
12. **Prefer curated, typed wrappers to indiscriminate PRESTO coverage.** Not every PRESTO routine deserves an MCP tool — pick ones with clear inputs/outputs, validate them, and ship tests. Untyped catch-alls are out of scope.
13. **New routines must be verified against the configured Docker image before being marked `stable`.** Default to `[experimental]` (or `[advanced]`) in the `@mcp.tool` description until an E2E smoke (or a `presto.validate_environment` run) confirms availability in `alex88ridolfi/presto5:png` (or the configured successor).

## What NOT to touch

- `data/` — real telescope observations. Never write. Never delete.
- `DeepResearch-MCPServer.md`, `deep-research-report.md` — research artifacts. Reference only.
- `docker.sock` — do not mount it anywhere.
- Don't add PulsarX, TransientX, riptide, Heimdall, PULSAR_MINER, or DRAFTS++ in MVP.
- Don't add an HTTP transport in MVP; stdio only.

## Setup

```bash
uv sync --extra dev
```

If `uv` is unavailable:
```bash
python -m venv .venv
.venv/Scripts/activate   # Windows
pip install -e ".[dev]"
```

## Develop

```bash
ruff check .
pytest -q                          # unit + integration
pytest -q tests/e2e --run-e2e      # E2E with Docker + real data
uv run python -m presto_mcp.server # boot MCP server (stdio)
```

## Validate (acceptance)

- `pytest -q` green.
- `pytest -q tests/e2e --run-e2e` green on a machine with Docker + `alex88ridolfi/presto5:png` + `data/57762_12049_J0532+3305_000022.fil`.
- `uv run python -m presto_mcp.server` boots without error.
- MCP Inspector (`npx @modelcontextprotocol/inspector ...`) lists `presto.readfile`, `presto.rfifind`, `presto.prepfold`, `presto.list_runs`, `presto.get_run_manifest`.
- Calling `presto.readfile` on `57762_12049_J0532+3305_000022.fil` returns `central_freq_mhz ≈ 1564.25`, `num_channels == 672`, `source_name == "J0532+3305"`.
- Calling `presto.rfifind { time: 2.0 }` on the same file produces `.mask`, `.rfi`, `.stats` in `runs/<id>/artifacts/`.
- `runs/<id>/manifest.json` exists for every invocation.
- Resources `presto://runs/<id>/{manifest,stdout,stderr,artifacts/<f>}` readable from MCP Inspector.

## Where to look

- `src/presto_mcp/docker_backend.py` — security-critical argv builder + `subprocess.run`.
- `src/presto_mcp/path_security.py` — security-critical traversal guards.
- `src/presto_mcp/executor.py` — orchestration of a single run.
- `src/presto_mcp/parsers/` — stdout-only PRESTO parsers (read-only contract against captured fixtures).
- `src/presto_mcp/server.py` — only file that imports FastMCP.
- `tests/fakes/fake_docker_backend.py` — drop-in replacement for the Docker backend in tests.
- `tests/fixtures/stdout/` — committed real-PRESTO stdout for parser contract tests.

## Style

- Pydantic v2 models for all schemas.
- Async at the MCP edge (`async def` tools), blocking subprocess inside `asyncio.to_thread`.
- Pin FastMCP to an exact version in `pyproject.toml` (pre-1.0, breaks frequently).
- Ruff defaults; no extra formatters.
