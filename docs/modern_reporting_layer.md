# Modern Reporting Layer

PRESTO's native outputs are scientifically complete but not designed as modern,
user-friendly artifacts. The reporting layer sits **on top of** PRESTO (it never
modifies PRESTO) and turns raw runs into clean, astronomer-facing deliverables.

## Three things, do not confuse them

| Term | What it is | Where |
|------|-----------|-------|
| **PRESTO raw outputs** | `.dat`, `.fft`, `.inf`, `.mask`, `.pfd`, `.singlepulse`, `.ps` … produced by PRESTO binaries. Internal. | `runs/<run_id>/` |
| **MCP modern artifacts** | `summary.json`, `candidates.csv`, PNG visuals, waterfalls, `report.html`, `report.md`. Curated, astronomer-facing. | `outputs/<run_id>/` |
| **Modern report bundle** | One orchestrated set of modern artifacts for a run, governed by an `ArtifactPolicy`. | `outputs/<run_id>/` + `manifest.json` |

See [artifact_policy.md](./artifact_policy.md) for the directory contract.

## Module layout

```
src/presto_mcp/reporting/
  schemas.py               Pydantic models (Candidate, Artifact, ArtifactPolicy,
                           RunReportSummary, ReportManifest, ...)
  artifact_policy.py       route_intention(): intent flags -> ArtifactPolicy
  artifact_manager.py      ArtifactManager: owns outputs/<run_id>/, extension
                           allowlist, traversal guard, manifest.json
  candidate_parser.py      parse .singlepulse(.gz), ACCEL_*, .bestprof,
                           groups.txt, cands.txt -> Candidate; candidates.csv
  summary_builder.py       build summary.json from readfile / .inf / manifests
  visual_builder.py        collect PNG, convert .ps/.eps (Ghostscript), thumbnails
  waterfall_builder.py     per-candidate waterfalls (PNG/PDF) via Docker waterfaller
  html_report_builder.py   offline report.html (embedded CSS + vanilla JS)
  markdown_report_builder.py  lightweight report.md
  bundle.py                generate_bundle(): orchestrates the whole layer
```

## The 7 MCP tools

| Tool | Produces |
|------|----------|
| `presto.export_candidates_csv` | `candidates.csv` |
| `presto.generate_summary_json` | `summary.json` |
| `presto.generate_visual_artifacts` | `visuals/*.png` + `thumbnails/*.png` |
| `presto.generate_candidate_waterfalls` | `waterfalls/<id>.png` (+ `.pdf`) — **quicklook only**, not a canonical single-pulse diagnostic (see note below) |
| `presto.generate_report_html` | `report.html` (+ summary, csv, visuals) |
| `presto.generate_report_markdown` | `report.md` |
| `presto.generate_modern_report_bundle` | the full bundle (intention-routed) |

All seven read one or more `runs/<run_id>/` workdirs (passed as `run_ids`
and/or `workdir`) and publish into a fresh `outputs/<run_id>/`. They never run
PRESTO except `generate_candidate_waterfalls`, which reuses the **containerized**
`presto.waterfaller` to render plots (no host plotting dependency).

`generate_modern_report_bundle` is the preferred tool for any "modern report",
"HTML report", "dashboard" or "full bundle" request.

### Quicklook vs. canonical single-pulse diagnostic

`presto.generate_candidate_waterfalls` is a **bulk quicklook**. It picks
``(start, duration, dm)`` windows from a candidate table (DM/SNR filters,
top-N) and invokes the low-level `presto.waterfaller` for each one. Useful
for triaging many events, but the selection logic is MCP-side, not PRESTO's
diagnostic semantics.

For a canonical single-pulse diagnostic of one candidate, prefer the PRESTO
chain `single_pulse_search → rrattrap → make_spd → plot_spd`. The `.spd`
file produced by `make_spd` is PRESTO's authoritative single-pulse artifact;
`plot_spd` renders the full diagnostic (waterfall + sub-band view + DM-time
plot + profile). When `.spd` files are present in the supplied `run_ids`,
`generate_modern_report_bundle` will surface the plot_spd output instead of
the quicklook.

## Candidate sources

`candidate_parser` consolidates **every** parseable candidate (not only the
best) from:

- `*.singlepulse` / `*.singlepulse.gz` — single-pulse events
- `*_ACCEL_<zmax>` / `*.txtcand` — accelsearch candidates
- `*.bestprof` — prepfold folded candidates
- `groups.txt` — rrattrap RRAT groups
- `cands.txt` — ACCEL_sift survivors

Unknown scientific parameters stay `null` — they are **never invented**. With
zero candidates, `candidates.csv` is still written (header only).

## Conservative science language

Reports never claim a discovery. They distinguish *plausible candidates*,
*likely RFI/noise* and *insufficient evidence*, and always say candidates
require human inspection. No "confirmed FRB / pulsar / transient".

## Observability integration

Each bundle creates a `RunTracker` (see the observability layer): the bundle's
own steps, the consolidated PRESTO runs and the waterfall commands produce a
live `status.md` + `timeline.json`, mirrored into `outputs/<run_id>/`. The
report `manifest.json` records `status_md`, `timeline_json` and `log_paths`;
`summary.json` records `logs_available` and `status_file`.

## Example prompts

1. **Candidates, no plots** — "Analyze this FITS file as an unknown radio
   observation and export all detected candidates to CSV. Do not generate
   plots." → `export_candidates_csv`.
2. **Candidates + diagnostics** — "…search for plausible candidates, export
   candidates.csv, and generate PNG diagnostics." → bundle, `wants_candidates` +
   `wants_visuals`.
3. **Waterfalls** — "…generate inferno-color waterfalls as PDF and PNG for all
   detected single-pulse events." → `generate_candidate_waterfalls`,
   `candidate_selection=all`, `export_pdf=true`.
4. **Full modern report** — "…run the appropriate PRESTO workflow, export all
   candidates, generate visuals, produce waterfalls and create a modern HTML
   report." → `generate_modern_report_bundle`, `wants_report` + `wants_waterfalls`.
5. **No extra files** — "Analyze this file but do not create extra artifacts.
   Report only textual findings." → bundle, `wants_no_extra_files`.
