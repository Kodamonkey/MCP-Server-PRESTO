# presto-mcp

A typed, sandboxed [Model Context Protocol](https://modelcontextprotocol.io) server that lets LLMs run real **PRESTO** (pulsar / radio-astronomy) tools inside Docker. Every run is isolated (`--network none`, read-only data mount, CPU/memory caps), logged to `runs/<run_id>/`, and exposed as MCP resources.

> **PRESTO-only** — not PrestoDB, Apache Pulsar, PulsarX, TransientX, riptide, Heimdall, or PULSAR_MINER.

---

## Quick start

**1. Install**

```bash
git clone <your-fork-or-repo-url>
cd MCP-Server-PRESTO
uv sync --extra dev
docker pull alex88ridolfi/presto5:png
```

Put observation files in `data/` (or set `PRESTO_DATA_DIR` in `.env` — copy from `.env.example`).

**2. Connect an MCP client**


| Client             | What to do                                                                                                                                                                                                   |
| ------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Cursor**         | Copy `[examples/mcp/cursor_mcp.example.json](examples/mcp/cursor_mcp.example.json)` → `.cursor/mcp.json`, replace `REPLACE_WITH_REPO_ROOT` with the absolute repo path, enable **presto** in Settings → MCP. |
| **Claude Desktop** | Merge the `presto` block from `[examples/mcp/claude_desktop_config.example.json](examples/mcp/claude_desktop_config.example.json)` into your MCP config; same path replacement. Restart the app.             |


More detail (Windows paths, venv fallback): `[examples/mcp/README.md](examples/mcp/README.md)`.

**3. Try it in the MCP Inspector (no client setup)**

```bash
npx @modelcontextprotocol/inspector uv run python -m presto_mcp.server
```

**4. Ask your LLM (or call tools yourself)**

Example prompts:

- *“Run `presto.readfile` on `57762_12049_J0532+3305_000022.fil` and summarize the metadata.”*
- *“Run `presto.rfifind` on that file with `time: 2.0`, then show the mask stats.”*
- *“Plot a 2 s waterfall at DM 50 starting at t=10 s with `presto.waterfaller`.”*

Paths are **relative to `data/`** (no absolute paths, no `..`). Outputs land in `runs/<run_id>/artifacts/` and are linked in the tool response.

Long jobs (~60 s+ on large `.fil` files): pass `"background": true`, then poll `presto.get_run_manifest` with the returned `run_id` until `status` is `SUCCESS`, `FAILED`, or `TIMEOUT`.

---

## MCP tools


| Tool                         | Purpose                                             |
| ---------------------------- | --------------------------------------------------- |
| **Inspection**               |                                                     |
| `presto.readfile`            | Parse filterbank / PSRFITS header metadata          |
| `presto.list_runs`           | List recent runs (newest first)                     |
| `presto.get_run_manifest`    | Full manifest for one `run_id`                      |
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
| `presto.rrattrap`            | Group single-pulse events                           |
| `presto.make_spd`            | Build single-pulse diagnostic `.spd`                |
| `presto.plot_spd`            | Render SPD plot (PNG/PS)                            |
| `presto.waterfaller`         | Dynamic-spectrum (waterfall) PNG around a candidate |
| **Data prep (new)**          |                                                     |
| `presto.psrfits2fil`         | PSRFITS → SIGPROC `.fil`                            |
| `presto.downsample_filterbank` | Factor-downsample a `.fil` (debug / fast iter)    |
| `presto.fb_truncate`         | Cut a sample window from a `.fil`                   |
| **RFI (new)**                |                                                     |
| `presto.rfifind_stats`       | Structured `bad_channels` / `bad_intervals` summary |
| `presto.weights_to_ignorechan` *(experimental)* | `.weights`/`.mask` → ignorechan list |
| `presto.makezaplist` *(experimental)* | Build `.zaplist` from `.birds`             |
| **Fold QC (new)**            |                                                     |
| `presto.pfd2png` *(experimental)* | `.pfd` → PNG/PS (image-dependent)              |
| `presto.pfdzap` *(experimental)* | Strict interval/channel zapping of a `.pfd`     |
| **Advanced (new)**           |                                                     |
| `presto.fourier_fold` *(experimental)* | Fold `.fft` at known (period\|freq, dm)    |
| `presto.sum_profiles` *(experimental)* | Combine multiple `.bestprof` / `.prof`     |
| `presto.search_bin` *(advanced)* | Phase-modulation / sideband search for binaries |


Tools tagged *(experimental)* / *(advanced)* may not be available in every PRESTO image — run `presto.validate_environment` first.

**Chaining runs:** tools that consume prior outputs take paths like `<run_id>/artifacts/file.dat` relative to `runs/` (see each tool’s parameter docs in the Inspector or client).

### MCP resources


| URI                                           | Contents                                                   |
| --------------------------------------------- | ---------------------------------------------------------- |
| `presto://runs/{run_id}/manifest`             | `manifest.json`                                            |
| `presto://runs/{run_id}/stdout`               | PRESTO stdout                                              |
| `presto://runs/{run_id}/stderr`               | PRESTO stderr                                              |
| `presto://runs/{run_id}/artifacts/{filename}` | One artifact (text inline; large/binary → JSON descriptor) |


---

## Prerequisites

- **Python 3.11+**
- **[uv](https://github.com/astral-sh/uv)**
- **Docker** running on the host
- Image: `docker pull alex88ridolfi/presto5:png`

```bash
docker run --rm alex88ridolfi/presto5:png which readfile rfifind prepfold
```

On Windows with OneDrive: ensure `data/` files are **“Always keep on this device”** (0-byte placeholders fail the startup check).

---

## Run the server manually

```bash
uv run python -m presto_mcp.server
```

Loads `PRESTO_*` from `.env` and the environment, creates `runs/`, `outputs/`, `logs/`, runs a health check, then speaks MCP over stdio.

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

## Utilities, resources and prompts

Beyond the PRESTO-binary tools, the server exposes utility tools, navigation resources, and MCP prompts.

**Utility tools** (no Docker, no PRESTO execution) — see [TOOLS.md](./TOOLS.md):

```text
presto.validate_environment    # OK/WARN/ERROR per-check report (settings, dirs, docker, image, policies)
presto.list_data_files         # index files under PRESTO_DATA_DIR
presto.summarize_run           # structured per-run summary + next_suggested_tools
presto.inspect_artifacts       # per-artifact index with resource URIs
```

Quick check from Inspector:

```text
presto.validate_environment(check_image=true)
presto.list_data_files(limit=20, extensions=[".fil",".fits"])
```

**Navigation resources** — see [RESOURCES.md](./RESOURCES.md):

```text
presto://data                              # JSON index of DATA_DIR
presto://runs                              # JSON index of recent runs
presto://runs/{run_id}/summary             # RunStructuredSummary JSON
presto://runs/{run_id}/artifacts           # ArtifactSummary list (no contents)
```

**Prompts** — see [PROMPTS.md](./PROMPTS.md). Six guidance prompts (`presto.inspect_observation_plan`, `presto.single_pulse_search_plan`, `presto.periodic_search_plan`, `presto.fold_known_candidate_plan`, `presto.explain_failed_run`, `presto.generate_candidate_report_plan`). They appear automatically in MCP Inspector and any client that surfaces prompts. **Prompts are guidance — the MCP server does not orchestrate or auto-execute.**

**Separation of responsibilities.** The MCP layer ships atomic, sandboxed capabilities (tools), navigable state (resources), and reusable guidance (prompts). Stateful / adaptive orchestration (looping over candidates, branching on results, retries with parameter tweaks) belongs to a future LangGraph (or equivalent) layer above this MCP — not inside it.

---

## Security (summary)

- Inputs validated by `path_security` — no absolute paths, no `..`, only under `DATA_DIR` or staged run artifacts.
- Execution: `subprocess.run(argv, shell=False)` only; no generic shell tool.
- Docker: `--network none`, `no-new-privileges`, `--pids-limit 256`, read-only `data/` bind.
- Typed errors only — no raw stack traces to clients.

Details: [ARCHITECTURE.md](./ARCHITECTURE.md). Agent conventions: [AGENTS.md](./AGENTS.md).

---

## Limits

- **Stdout parsers only** for structured fields; binary products (`.mask`, `.pfd`, PNGs) are artifacts/resources, not decoded server-side.
- `**prepfold` Mode A** — known period + DM; accel-cand folding is not wired yet.
- **STDIO only** — no HTTP transport.
- `**list_runs`** walks `runs/*/manifest.json` (fine for thousands of runs).

---

## Project layout


| Path                               | Role                                                     |
| ---------------------------------- | -------------------------------------------------------- |
| `src/presto_mcp/server.py`         | FastMCP entrypoint                                       |
| `src/presto_mcp/docker_backend.py` | Docker argv + subprocess                                 |
| `src/presto_mcp/path_security.py`  | Path guards                                              |
| `src/presto_mcp/executor.py`       | Run orchestration                                        |
| `src/presto_mcp/tools/`            | One module per PRESTO tool                               |
| `examples/mcp/`                    | Cursor / Claude Desktop config templates                 |
| `data/`                            | Observation inputs (read-only, never committed if large) |


---

## License

MIT — see `pyproject.toml`.