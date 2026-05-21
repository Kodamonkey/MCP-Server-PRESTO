# Contributing

This is a **PRESTO-only** MCP server: a typed, sandboxed, reproducible provider
of PRESTO capabilities. Adaptive orchestration is explicitly out of scope (it
belongs to a future LangGraph layer above this MCP). Read `CLAUDE.md` and
`ARCHITECTURE.md` before starting.

## Non-negotiable rules

- **No generic executor.** Never add `run_command`, `exec`, `bash`,
  `python_exec`, `arbitrary_presto_command`, etc. Each PRESTO binary gets its
  own typed tool.
- **No shell.** `subprocess.run(..., shell=False)`, argv lists only.
- **No host execution.** PRESTO runs only inside the configured Docker image.
- **No `docker.sock` mount.** The server invokes the host `docker` CLI.
- **No new Docker image, no LangGraph, no HTTP transport** in this repo.
- **`data/` is read-only.** Never delete, never write, always mount `:readonly`.
- All new output goes to `runs/<run_id>/artifacts/`.
- Typed errors only — surface `PathSecurityError`, `DockerInvocationError`,
  `ParserError`, `PolicyViolationError`; never leak raw tracebacks.

## The anti-bloat rule

The goal is **fewer, better tools**, not maximal PRESTO coverage. A new tool is
accepted only if **every** item below is true:

1. It corresponds to an official PRESTO routine **or** a recurring scientific
   need (e.g. candidate review).
2. It has fully typed Pydantic input **and** output models.
3. It uses no generic shell and no host execution.
4. All model/user paths go through `path_security` resolution.
5. It produces traceable artifacts (a manifest, or a typed result for
   no-Docker utility tools).
6. If it depends on image contents, it is **readiness-gated** via
   `runtime_checks` and fails fast with a controlled, actionable error.
7. It has unit tests (parser / input validation) **and** at least one
   integration test using `FakeDockerBackend`.
8. It has documentation in `TOOLS.md` (status, routine, I/O, readiness,
   next-suggested tools, a minimal example).
9. It does not duplicate an existing tool. Extend utilities / prompts /
   resources before adding a new tool.

If you cannot satisfy all nine, the work belongs in an existing tool
(hardening) or a prompt — not a new tool.

## Definition of done (per tool)

1. Typed function under `src/presto_mcp/tools/<name>.py`.
2. Registered in `server_tools.py`.
3. Result model in `models.py`; numeric guards in `policies.py`.
4. Parser under `parsers/` with a `notes: list[str]` fallback path.
5. `runtime_checks._TOOL_DEPS` entry if it depends on image contents.
6. Unit test + integration test (`FakeDockerBackend`) + an
   `@pytest.mark.e2e` smoke test where feasible.
7. Docs updated: `TOOLS.md`, and `README.md` / `RUNTIME_COMPATIBILITY.md` if
   the tool is image-dependent.
8. `CHANGELOG.md` `Unreleased` section updated.

## Local checks

```bash
uv sync --extra dev
uv run ruff check .
uv run pytest -q
uv run python -m presto_mcp.server      # must boot
```

E2E (needs Docker + the PRESTO image + real data):

```bash
uv run pytest -q tests/e2e --run-e2e
```

CI runs `ruff` + `pytest` on every PR. The image-probing workflow
`runtime-compatibility.yml` is manual (`workflow_dispatch`).

## Verifying image-dependent tools

Before marking a tool `stable`, verify it against the configured image with
`presto.validate_environment(include_tool_readiness=true)` or an e2e smoke
test. Until then, keep it `[experimental]` / `[advanced]` /
`[image-dependent]` in the `@mcp.tool` description.
