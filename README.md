# presto-mcp

A typed, sandboxed [Model Context Protocol](https://modelcontextprotocol.io) server that lets LLMs run real **PRESTO** (pulsar / radio-astronomy) tools inside Docker. Every run is isolated (`--network none`, read-only data mount, CPU/memory caps), logged to `runs/<run_id>/`, and exposed as MCP resources.

> **PRESTO-only** — not PrestoDB, Apache Pulsar, PulsarX, TransientX, riptide, Heimdall, or PULSAR_MINER.

---

## Installation (canonical)

One consistent way to install, configure, and connect clients. Designed for onboarding and local production use.

### Decisions (non-negotiable)

| # | Decision | Reason |
|---|----------|--------|
| 1 | **All config lives in `<repo>/.env`** (copy from `.env.example`) | Single source of truth; do not duplicate `PRESTO_*` in Cursor/Claude JSON |
| 2 | **Single startup command** | `uv run --directory <REPO> python -m presto_mcp.server` |
| 3 | **Always use `--directory <REPO>`** | MCP client does not depend on `cwd`; it loads the package and `.env` from the clone |
| 4 | **Default data location is `./data`** | If data is elsewhere, only change `PRESTO_DATA_DIR` in `.env` |
| 5 | **Client JSON = repo path only** | Replace `REPLACE_WITH_REPO_ROOT`; no `"env"` block |
| 6 | **Client launches server** | You do not need to keep `uv run ...` open in a terminal for daily use |

### 1. Requirements

- Python 3.11+, [uv](https://docs.astral.sh/uv/), Docker running
- Image: `docker pull alex88ridolfi/presto5:png`

### 2. Clone and install

```bash
git clone <your-fork-or-repo-url>
cd MCP-Server-Presto
uv sync --extra dev
docker pull alex88ridolfi/presto5:png
```

### 3. Configure (only `.env`)

```bash
cp .env.example .env   # Windows: copy .env.example .env
```

Edit `.env` if needed:

- **`PRESTO_DATA_DIR`** — defaults to `./data` (`.fil` / `.fits` files inside the repo).
- If your observations are **outside** the repo, set the absolute path here (typically the only extra path you need).

Everything else (`runs/`, CPUs, memory, Docker image) can stay at defaults.

Put observation files in `data/` (or in the directory you set in `PRESTO_DATA_DIR`).

**Windows + OneDrive:** right-click the data folder -> *Always keep on this device* (0-byte placeholders fail the health check).

### 4. Verify startup

From the repo root:

```bash
uv run --directory . python -m presto_mcp.server
```

You should see `presto-mcp starting` and the `data=...` path. Press Ctrl+C to stop. If startup fails, fix `.env` or Docker before continuing.

### 5. Test tools (MCP Inspector)

Without configuring Cursor or Claude first:

```bash
npx @modelcontextprotocol/inspector uv run --directory . python -m presto_mcp.server
```

Open the URL printed by Inspector. Try `presto.validate_environment` and `presto.readfile` with a filename under `data/`.

### 6. Connect Cursor or Claude Desktop

Copy the template and replace **only** `REPLACE_WITH_REPO_ROOT` with the absolute clone path (use `\\` in Windows JSON).

| Client | Template | Destination |
|--------|----------|-------------|
| **Cursor** | [examples/mcp/cursor_mcp.example.json](examples/mcp/cursor_mcp.example.json) | `.cursor/mcp.json` in the repo root |
| **Claude Desktop** | [examples/mcp/claude_desktop_config.example.json](examples/mcp/claude_desktop_config.example.json) | Merge into the system `claude_desktop_config.json` |

Enable the **presto** server (Cursor: Settings -> MCP). Fully restart Claude Desktop.

Extra details (`uv.exe` path, venv option): [examples/mcp/README.md](examples/mcp/README.md).

### 7. Use with the LLM

Prompt examples:

- *“Run `presto.readfile` on `57762_12049_J0532+3305_000022.fil` and summarize the metadata.”*
- *“Run `presto.rfifind` on that file with `time: 2.0`, then show the mask stats.”*

Filenames are **relative to `PRESTO_DATA_DIR`** (no absolute paths and no `..`). Outputs go to `runs/<run_id>/artifacts/`.

For long jobs: set `"background": true` and poll with `presto.get_run_manifest` until `SUCCESS` / `FAILED` / `TIMEOUT`.

### Which command to use when

| Goal | Command |
|----------|---------|
| Verify installation | `uv run --directory . python -m presto_mcp.server` |
| Test tools in browser | `npx @modelcontextprotocol/inspector uv run --directory . python -m presto_mcp.server` |
| Use with Cursor / Claude | Client runs the same `uv run --directory <REPO> ...` (JSON template); **no** extra terminal required |

---

## MCP tools

The server registers **38** `presto.*` tools. Utility tools (no Docker) are listed first; the rest invoke PRESTO inside the configured image.

| Tool                         | Purpose                                             |
| ---------------------------- | --------------------------------------------------- |
| **Triage & utilities**       |                                                     |
| `presto.validate_environment` | Docker/image checks + optional per-tool readiness  |
| `presto.list_data_files`     | Index files under `PRESTO_DATA_DIR`                 |
| `presto.readfile`            | Parse filterbank / PSRFITS header metadata          |
| `presto.list_runs`           | List recent runs (newest first)                     |
| `presto.get_run_manifest`    | Full manifest for one `run_id`                      |
| `presto.summarize_run`       | Structured run summary + `next_suggested_tools`     |
| `presto.inspect_artifacts`   | Per-artifact index with resource URIs               |
| `presto.compare_periods` *(utility)* | Cross-check period vs `.par` ephemerides   |
| `presto.binary_info` *(utility)* | Orbital summary from a binary `.par`          |
| `presto.compile_candidate_report_pdf` *(utility)* | Bundle run plots into one PDF |
| **RFI & prep**               |                                                     |
| `presto.rfifind`             | RFI search → `.mask`, `.rfi`, `.stats`, …           |
| `presto.prepdata`            | Dedisperse one DM → `.dat` + `.inf`                 |
| `presto.ddplan`              | DM trial plan (no input file)                       |
| `presto.prepsubband`         | Dedisperse a DM range → many `.dat` files           |
| **Search & fold**            |                                                     |
| `presto.realfft`             | FFT a `.dat` from a prior run → `.fft`              |
| `presto.accelsearch`         | Fourier / acceleration search on `.fft`             |
| `presto.sifting`             | Rank / dedupe ACCEL candidates                      |
| `presto.prepfold`            | Fold at known period + DM → `.pfd`                  |
| `presto.single_pulse_search` | Bright single-pulse search on `.dat` file(s)        |
| `presto.zapbirds`            | Apply zaplist to `.fft`                             |
| **Timing & transients**      |                                                     |
| `presto.get_toas`            | Times of arrival from `.pfd` + template             |
| `presto.rrattrap` *(experimental / image-dependent)* | Group single-pulse events      |
| `presto.make_spd`            | Build single-pulse diagnostic `.spd`                |
| `presto.plot_spd`            | Render SPD plot (PNG/PS)                            |
| `presto.waterfaller`         | Dynamic-spectrum (waterfall) PNG around a candidate |
| **Data prep**                |                                                     |
| `presto.psrfits2fil`         | PSRFITS → SIGPROC `.fil`                            |
| `presto.downsample_filterbank` | Factor-downsample a `.fil` (debug / fast iter)    |
| `presto.fb_truncate`         | Cut a sample window from a `.fil`                   |
| **RFI**                      |                                                     |
| `presto.rfifind_stats`       | Structured `bad_channels` / `bad_intervals` summary |
| `presto.weights_to_ignorechan` *(experimental)* | `.weights`/`.mask` → ignorechan list |
| `presto.makezaplist` *(experimental)* | Build `.zaplist` from `.birds`             |
| **Fold QC**                  |                                                     |
| `presto.pfd2png` *(experimental)* | `.pfd` → PNG/PS (image-dependent)              |
| `presto.pfdzap` *(experimental)* | Strict interval/channel zapping of a `.pfd`     |
| **Advanced**                 |                                                     |
| `presto.sum_profiles` *(experimental)* | Combine multiple `.bestprof` / `.prof`     |
| `presto.fourier_fold` *(experimental)* | Fold a `.fft` at a known candidate         |
| `presto.search_bin` *(advanced)* | Phase-modulation / sideband search for binaries |
| `presto.stacksearch` *(experimental / image-dependent)* | Stack search over many `.fft` |
| `presto.simple_zapbirds` *(experimental / image-dependent)* | Zap birdies from a `.fft` (on a staged copy) |

**Tool status taxonomy.** `stable` · `experimental` (awaiting image
verification) · `image-dependent` (correctness depends on image contents,
readiness-gated) · `advanced` (wide parameter space) · `utility` (no Docker).

### Tool profiles

`PRESTO_TOOL_PROFILE` (in `.env`) selects which tools the server exposes, so an
LLM agent chooses from a smaller, task-focused catalog instead of all 38 tools
at once.

| Profile | Tools exposed |
|---------|---------------|
| `all` (default) | All 38 tools. |
| `core` | Core set only (7 tools): `validate_environment`, `list_data_files`, `readfile`, `list_runs`, `get_run_manifest`, `summarize_run`, `inspect_artifacts`. |
| `rfi_prep` | Core + data-prep + RFI tools. |
| `periodic` | Core + periodic / acceleration search pipeline. |
| `single_pulse` | Core + single-pulse search pipeline. |
| `review_qc` | Core + candidate-review / known-pulsar tools. |
| `advanced` | Core + advanced / experimental tools. |

Every non-`all` profile includes the **core** set above, so
`presto.get_run_manifest` (needed for `background` polling) is always
available. An unknown value falls back to `all`.

### Runtime compatibility

Not every PRESTO image ships every routine, and some ship a script without the
internal Python module it imports. **Recommended first calls in any session:**

```text
presto.validate_environment(include_tool_readiness=true)
presto.list_data_files(limit=20)
presto.readfile(input_file="<your file>")
```

`presto.validate_environment` probes the image with lightweight Docker commands
and reports per-tool readiness (`runtime_compatibility.tool_readiness`).
Image-dependent tools (`rrattrap`, `stacksearch`, `simple_zapbirds`, and the
`accelsearch -wmax` jerk flag) check readiness first and fail fast with a
controlled, actionable error rather than a confusing traceback.

Known case: some PRESTO images expose `rrattrap.py` but cannot
`import presto.singlepulse`; `presto.rrattrap` then refuses to run and points
you at `presto.validate_environment`. See
[RUNTIME_COMPATIBILITY.md](./docs/RUNTIME_COMPATIBILITY.md) for the full picture.

**Chaining runs:** tools that consume prior outputs take paths like `<run_id>/artifacts/file.dat` relative to `runs/` (see each tool’s parameter docs in the Inspector or client).

### MCP resources

| URI | Contents |
| --- | --- |
| `presto://data` | JSON index of `PRESTO_DATA_DIR` |
| `presto://runs` | JSON index of recent runs |
| `presto://runs/{run_id}/manifest` | `manifest.json` |
| `presto://runs/{run_id}/stdout` | PRESTO stdout |
| `presto://runs/{run_id}/stderr` | PRESTO stderr |
| `presto://runs/{run_id}/summary` | `RunStructuredSummary` JSON |
| `presto://runs/{run_id}/artifacts` | Artifact index (no file contents) |
| `presto://runs/{run_id}/artifacts/{filename}` | One artifact (text inline; large/binary → JSON descriptor) |

Full reference: [RESOURCES.md](./docs/RESOURCES.md).

**Docker sanity check** (optional, after install):

```bash
docker run --rm alex88ridolfi/presto5:png which readfile rfifind prepfold
```

Startup health checks call `docker info`, not only `docker --version`; the daemon must be running. `presto.validate_environment` reports CLI, daemon, and image checks separately.

---

## Run the server manually

```bash
uv run --directory . python -m presto_mcp.server
```

Loads `PRESTO_*` from `.env`, creates `runs/`, `outputs/`, `logs/`, runs a health check, then speaks MCP over stdio. For day-to-day use, let your MCP client spawn this command instead of running it yourself.

---

## Tests

```bash
uv run pytest -q              # unit + integration (no Docker)
uv run ruff check .
uv run pytest -q tests/e2e --run-e2e   # real Docker + data/
```

---

## One run on disk

```
runs/20260517T145912Z-OE2YWN/
├── manifest.json    # docker argv, status, artifacts, timings
├── stdout.log
├── stderr.log
└── artifacts/
    └── waterfall.png
```

`run_id` format: `YYYYMMDDTHHMMSSZ-<6-char base32>` (UTC + entropy).

---

## Utilities and prompts

Utility-tool parameters and examples: [TOOLS.md](./docs/TOOLS.md).

Quick Inspector checks:

```text
presto.validate_environment(include_tool_readiness=true)
presto.list_data_files(limit=20, extensions=[".fil",".fits"])
```

**Prompts** (12 guidance templates, no auto-execution): [PROMPTS.md](./docs/PROMPTS.md). They appear in MCP Inspector and any client that surfaces prompts.

**Separation of responsibilities.** The MCP layer ships atomic, sandboxed capabilities (tools), navigable state (resources), and reusable guidance (prompts). Stateful / adaptive orchestration (looping over candidates, branching on results, retries with parameter tweaks) belongs to a future LangGraph (or equivalent) layer above this MCP — not inside it.

---

## Security (summary)

- Inputs validated by `path_security` — no absolute paths, no `..`, only under `DATA_DIR` or staged run artifacts.
- Execution: `subprocess.run(argv, shell=False)` only; no generic shell tool.
- Docker: `--network none`, `no-new-privileges`, `--pids-limit 256`, read-only `data/` bind, optional read-only `/runs` bind for prior artifacts.
- Concurrency: `PRESTO_MAX_CONCURRENT_RUNS` gates Docker invocations process-wide (default `2`).
- Typed errors only — no raw stack traces to clients.

Details: [ARCHITECTURE.md](./docs/ARCHITECTURE.md). Agent conventions: [AGENTS.md](./AGENTS.md).

---

## Limits & known limitations

- **Stdout parsers only** for structured fields; binary products (`.mask`, `.pfd`, PNGs) are artifacts/resources, not decoded server-side.
- **`prepfold` Mode A** — known period + DM; accel-cand folding is not wired yet.
- **STDIO only** — no HTTP transport.
- **`list_runs`** walks `runs/*/manifest.json` (fine for thousands of runs).
- Stdout/stderr are still captured in memory before writing logs; diagnostics returned to clients are bounded, full logs remain in run resources.
- **Image-dependent tools** (`rrattrap`, `stacksearch`, `simple_zapbirds`, `accelsearch -wmax`) only work when the configured PRESTO image provides the routine — check `presto.validate_environment(include_tool_readiness=true)`. See [RUNTIME_COMPATIBILITY.md](./docs/RUNTIME_COMPATIBILITY.md).
- `presto.binary_info` `make_plot` is not supported (it is a no-Docker utility tool); orbital plots come from `presto.prepfold` / `presto.pfd2png`.
- Adaptive orchestration (resume/restart, autonomous search) is **out of scope** — it belongs to a future LangGraph layer above this MCP.

Contributing — read [CONTRIBUTING.md](./CONTRIBUTING.md) (especially the
anti-bloat rule). Release history — [CHANGELOG.md](./CHANGELOG.md).

---

## Project layout

| Path | Role |
| --- | --- |
| `pyproject.toml` / `uv.lock` | Dependencies and reproducible lockfile (`uv sync`) |
| `.env.example` | Template for all `PRESTO_*` settings |
| `AGENTS.md` | Canonical instructions for coding agents |
| `CONTRIBUTING.md` | Contribution rules and anti-bloat policy |
| `docs/` | Architecture, tools, prompts, resources, runtime compatibility |
| `src/presto_mcp/server.py` | FastMCP entrypoint (stdio) |
| `src/presto_mcp/server_tools.py` | MCP tool registration (38 tools) |
| `src/presto_mcp/server_resources.py` | MCP resource registration |
| `src/presto_mcp/server_prompts.py` | MCP prompt registration (12 prompts) |
| `src/presto_mcp/tool_metadata.py` | Tool profiles (`PRESTO_TOOL_PROFILE`) |
| `src/presto_mcp/docker_backend.py` | Docker argv + subprocess |
| `src/presto_mcp/path_security.py` | Path guards |
| `src/presto_mcp/executor.py` | Run orchestration |
| `src/presto_mcp/tools/` | One module per tool |
| `tests/` | Unit, integration, and e2e tests |
| `scripts/runtime_compat_report.py` | Manual image compatibility report (CI workflow) |
| `examples/mcp/` | Cursor / Claude Desktop JSON templates |
| `data/` | Observation inputs (read-only; often not committed) |
| `runs/` | Per-invocation manifests, logs, artifacts (runtime) |


---

## License

MIT — see `pyproject.toml`.
