# Architecture

## Goal

Give an LLM safe, typed, reproducible access to the PRESTO pulsar/radio-astronomy toolchain through MCP. Every invocation is sandboxed in Docker and produces an auditable on-disk manifest.

## Layers

```
┌──────────────────────────────────────────────────────────────┐
│ MCP client (Claude Desktop / MCP Inspector / Cursor)         │
└──────────────────────────┬───────────────────────────────────┘
                           │ JSON-RPC over stdio
┌──────────────────────────▼───────────────────────────────────┐
│ presto_mcp.server (FastMCP entrypoint)                       │
│   - delegates registration to server_tools/resources/prompts │
│   - owns FastMCP import, settings/backend singletons         │
└──────────────────────────┬───────────────────────────────────┘
                           │ async wrappers → asyncio.to_thread
┌──────────────────────────▼───────────────────────────────────┐
│ presto_mcp.server_tools + tools.*                            │
│   typed PRESTO wrappers + utility tools                      │
└──────────────────────────┬───────────────────────────────────┘
                           │
┌──────────────────────────▼───────────────────────────────────┐
│ presto_mcp.executor   (orchestration)                        │
│   1. resolve_input_path    (path_security)                   │
│   2. create_run_dir        (path_security)                   │
│   3. build DockerInvocation (docker_backend.build_invocation)│
│   4. backend.run()         (docker_backend)                  │
│   5. parse stdout          (parsers/)                        │
│   6. write_manifest        (manifest)                        │
│   7. assemble ToolRunResult                                  │
└──────────────────────────┬───────────────────────────────────┘
                           │ subprocess.run(argv, shell=False, timeout=N)
┌──────────────────────────▼───────────────────────────────────┐
│ Docker CLI (host)                                            │
│ → container: alex88ridolfi/presto5:png                       │
│      --network none --pids-limit 256                         │
│      --security-opt no-new-privileges                        │
│      --cpus N --memory Mm --stop-timeout 5                   │
│      --mount type=bind,src=<DATA>,dst=/data,readonly         │
│      --mount type=bind,src=<RUN_DIR>,dst=/outputs            │
│      optional --mount type=bind,src=<RUNS>,dst=/runs,ro      │
│      typed PRESTO command argv                               │
└──────────────────────────────────────────────────────────────┘
```

The host never executes PRESTO binaries. The container never sees anything outside `/data` (read-only) and `/outputs` (read-write).

## Flow of one tool call

1. **MCP client → server.py.** FastMCP routes the call to an `async def presto_<tool>(input: <ToolInput>) -> ToolRunResult[T]`.
2. **server.py → tools/*.py.** Pure async function. Validates input via Pydantic.
3. **tools/*.py → executor.py.** Inside `asyncio.to_thread`, the executor:
   - calls `path_security.resolve_input_path(input.input_file)` against `DATA_DIR`,
   - calls `path_security.create_run_dir(tool_name)` → `(run_id, run_dir)`,
   - builds a `DockerInvocation` (image, argv, cpus, memory, container name),
   - calls `docker_backend.run(invocation, timeout_s)`,
   - on success: parses stdout with `parsers/<tool>_parser`,
   - writes `manifest.json` regardless of outcome,
   - builds a `ToolRunResult[T]` carrying typed result + resource URIs.
4. **server.py → MCP client.** FastMCP serializes the `ToolRunResult` as `structuredContent`, attaches a short human string, returns.

## Security model

| Layer | Defense |
|-------|---------|
| Input path | `path_security.resolve_input_path` rejects absolute, `..`, backslash-prefixed; `Path.resolve(strict=True)`; must be under `DATA_DIR.resolve()`; case must match on-disk casing. |
| Tool surface | One typed tool per binary. No `run_command`. No string concatenation. |
| Subprocess | `shell=False`, argv list only. Timeout enforced. On timeout, Docker container is killed and manifest status is `TIMEOUT`. Docker calls are gated by `PRESTO_MAX_CONCURRENT_RUNS`. |
| Container | `--network none`, `--security-opt no-new-privileges`, `--pids-limit 256`, `--cpus`, `--memory`, named container, `--rm`. |
| Mounts | `data/` is `readonly`. Run dir is `rw` at `/outputs`. Prior-run artifact consumers may also mount `runs/` read-only at `/runs`. |
| Resources | `presto://runs/{id}/artifacts/{filename}` rechecks `ensure_inside_root(run_dir/artifacts, filename)` before reading. Large files return metadata only. |
| Errors | Typed: `PathSecurityError`, `DockerInvocationError`, `ParserError`, `PolicyViolationError`. No stack traces leak through MCP; non-zero Docker/PRESTO exits carry bounded diagnostics. |

## Manifest model

`runs/<run_id>/manifest.json`:

```json
{
  "schema_version": 1,
  "run_id": "20260516T143052Z-K7QM3A",
  "tool": "readfile",
  "status": "SUCCESS",
  "exit_code": 0,
  "started_at": "2026-05-16T14:30:52Z",
  "finished_at": "2026-05-16T14:30:54Z",
  "duration_s": 1.84,
  "timeout_s": 1800,
  "image": "alex88ridolfi/presto5:png",
  "image_digest": "sha256:...",
  "docker_argv": ["docker","run","--rm","--name","presto-...", "..."],
  "presto_argv": ["readfile","/data/57762_12049_J0532+3305_000022.fil"],
  "inputs": {"input_file": "C:/.../data/57762_..."},
  "container_inputs": {"input_file": "/data/57762_..."},
  "cpus": 4.0,
  "memory_mb": 8192,
  "stdout_path": "stdout.log",
  "stderr_path": "stderr.log",
  "artifacts": [],
  "error": null
}
```

Status values: `PENDING | RUNNING | SUCCESS | FAILED | TIMEOUT`.

## Tool surface

The server exposes typed PRESTO wrappers plus utility/navigation tools. Stable
core includes `readfile`, `rfifind`, `prepdata`, `ddplan`, `prepsubband`,
`realfft`, `accelsearch`, `single_pulse_search`, `sifting`, `prepfold`,
`list_runs`, and `get_run_manifest`. Additional data-prep, RFI, fold-QC,
timing, visualization, and advanced tools are registered in `server_tools.py`
and marked `[experimental]` / `[advanced]` where image availability is not
guaranteed.

Utility tools (`validate_environment`, `list_data_files`, `summarize_run`,
`inspect_artifacts`, `compare_periods`, `binary_info`,
`compile_candidate_report_pdf`) never execute PRESTO. Prompts remain guidance
only.

## Runtime capability checks

`runtime_checks.py` makes the server honest about an imperfect image. It runs
**lightweight one-off Docker probes** (`which <binary>`,
`python3 -c "import ..."`, `<binary> -h`) — never real PRESTO work — and turns
the results into structured `RuntimeCheck` / `ToolReadiness` /
`RuntimeCompatibilityResult` data. Probes reuse the same `build_invocation` +
`backend.run` path as a real run, so there is no new subprocess surface and no
change to `BackendProtocol`. Results are cached in-process per image tag for
~15 minutes.

Two consumers:

- **Preflight gates.** `presto.rrattrap`, `presto.stacksearch`,
  `presto.simple_zapbirds` call `get_tool_readiness` before doing work and fail
  fast with a controlled error if a dependency is missing. `presto.ddplan` and
  `presto.accelsearch` probe `<binary> -h` to gate image-dependent flags.
- **Diagnostics.** `presto.validate_environment(include_tool_readiness=true)`
  reports per-tool readiness so an agent can choose tools that will actually run.

A probe that times out yields `UNKNOWN` and is **fail-open** — a transient
Docker hiccup never permanently blocks a tool. See `RUNTIME_COMPATIBILITY.md`.

## Relationship to PULSAR_MINER

PULSAR_MINER is used **only as conceptual workflow inspiration — never as a
runtime dependency**. Nothing from it is imported or vendored. Two ideas are
borrowed:

- the stage taxonomy (RFI / BIRDIES / DEDISPERSION / SIFTING / FOLDING) as a
  vocabulary for summaries and reports;
- the known-pulsar cross-check, implemented here as a small, transparent
  combination of `presto.compare_periods` + `presto.binary_info` — not an
  opaque macro-pipeline.

Resume/restart, space/time estimation and full autonomous search remain the
responsibility of a future LangGraph orchestrator above this MCP, not of the
server itself.

## Parser strategy (MVP)

Stdout only. PRESTO's binary outputs (`.mask`, `.stats`, `.rfi`, `.pfd`, etc.) are surfaced as artifacts/resources but not parsed in MVP — a future phase can vendor the SIGPROC/RFIFIND binary readers.

- `readfile`: line-oriented `Key = Value` after a banner; `parsers/readfile_parser.py` maps known keys → typed `ReadfileMetadata`, preserves unknown keys in `raw_fields`.
- `rfifind`: extract mask filename / interval counts from stdout via regex; resolve `.mask`/`.rfi`/`.stats` filesystem-side by globbing the run-dir.

## Persistence

```
runs/
└── <run_id>/
    ├── manifest.json
    ├── stdout.log
    ├── stderr.log
    └── artifacts/
        ├── <prefix>.mask        (rfifind)
        ├── <prefix>.rfi
        ├── <prefix>.stats
        ├── <prefix>.ps          (rfifind, optional)
        ├── <prefix>.pfd         (prepfold)
        ├── <prefix>.pfd.ps      (prepfold)
        └── <prefix>.pfd.bestprof
```

`runs/` is the **internal workdir**: raw, complete, never published directly.

### Modern reporting layer (`outputs/`)

The `reporting/` package turns a run into clean, astronomer-facing artifacts on
demand (7 `presto.*` tools). It treats `runs/` as read-only input and publishes
into a fresh `outputs/<run_id>/`:

```
outputs/<run_id>/
  manifest.json  summary.json  candidates.csv  report.html  report.md
  visuals/  thumbnails/  waterfalls/  candidates/<id>/  assets/
  presto_raw_exports/   (only when raw export is explicitly requested)
```

`ArtifactManager` enforces a public extension allowlist (`.json .csv .html .md
.png .pdf`); raw PRESTO files (`.dat`, `.fft`, `.pfd`, `.singlepulse`, `.ps`, …)
are never published by default. See [artifact_policy.md](./artifact_policy.md)
and [modern_reporting_layer.md](./modern_reporting_layer.md).

### Observability (`logs/`)

The `observability/` package writes a per-server-session structured log
(`logs/server/`) and, for each report run / client-grouped workflow, a per-run
timeline, tool-call / PRESTO-command / artifact / error JSONL streams and a live
`status.md` under `logs/runs/<run_id>/`. Human + JSONL logs run side by side with
rotation and secret redaction.

`list_runs` is `glob("runs/*/manifest.json") → load_manifest`. Stale `RUNNING`
manifests older than their timeout are reported as failed views without
rewriting history. No SQLite in MVP.

## Roadmap (next)

1. Native binary parsers for `.mask`/`.stats`/`.bestprof` (beyond stdout-only contracts).
2. Broader E2E coverage for image-dependent / experimental tools in CI.
3. Optional SQLite run index for fast filtering by tool/date/source.
4. Optional HTTP transport behind authentication (out of scope for stdio-only deployments).
5. Image-digest pinning + supply-chain verification.

Cross-tool orchestration (e.g. `rfifind → prepsubband → accelsearch → prepfold`) belongs in a client or LangGraph layer above this MCP — use prompts in [PROMPTS.md](./PROMPTS.md) for guidance, not in-server pipelines.
