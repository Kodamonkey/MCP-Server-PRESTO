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
│ presto_mcp.server (FastMCP)                                  │
│   - registers tools  (presto.readfile, .rfifind, .prepfold,  │
│                       .list_runs, .get_run_manifest)         │
│   - registers resources  (presto://runs/{id}/...)            │
└──────────────────────────┬───────────────────────────────────┘
                           │ async wrappers → asyncio.to_thread
┌──────────────────────────▼───────────────────────────────────┐
│ presto_mcp.tools.*  (pure async functions)                   │
│   readfile / rfifind / prepfold / list_runs                  │
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
│      readfile | rfifind | prepfold                           │
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
| Subprocess | `shell=False`, argv list only. Timeout enforced. On `TimeoutExpired` → `docker kill <name>` → manifest status `TIMEOUT`. |
| Container | `--network none`, `--security-opt no-new-privileges`, `--pids-limit 256`, `--cpus`, `--memory`, named container, `--rm`. |
| Mounts | `data/` is `readonly`. Run dir is `rw` at `/outputs`. Nothing else mounted. |
| Resources | `presto://runs/{id}/artifacts/{filename}` rechecks `ensure_inside_root(run_dir/artifacts, filename)` before reading. Large files return metadata only. |
| Errors | Typed: `PathSecurityError`, `DockerInvocationError`, `ParserError`, `PolicyViolationError`. No stack traces leak through MCP. |

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

## MVP tools

| Name                       | What it runs                                             | Result type          |
|----------------------------|----------------------------------------------------------|----------------------|
| `presto.readfile`          | `readfile /data/<file>`                                  | `ReadfileMetadata`   |
| `presto.rfifind`           | `rfifind -time <t> -o /outputs/<prefix> /data/<file>`    | `RfifindSummary`     |
| `presto.prepfold` (Mode A) | `prepfold -noxwin -p <p> -dm <dm> -o /outputs/<pre> ...` | `PrepfoldResult`     |
| `presto.list_runs`         | filesystem glob over `runs/`                             | `list[RunSummary]`   |
| `presto.get_run_manifest`  | load + return one manifest                               | `RunManifest`        |

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

`outputs/` is reserved for human-facing exports (future phase); MVP never writes there from MCP tools.

`list_runs` is `glob("runs/*/manifest.json") → load_manifest`. No SQLite in MVP.

## Roadmap (post-MVP)

1. Native binary parsers for `.mask`/`.stats`/`.bestprof`.
2. `presto.prepdata`, `presto.accelsearch`, `presto.single_pulse_search.py`.
3. Cross-tool workflows (chain `rfifind → prepsubband → accelsearch → prepfold`).
4. SQLite run index for fast filtering by tool/date/source.
5. Optional HTTP transport behind authentication.
6. Image-digest pinning + supply-chain verification.

Anything beyond this is explicitly out of scope until the MVP ships.
