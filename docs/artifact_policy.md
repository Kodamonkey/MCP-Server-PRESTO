# Artifact Policy

The modern reporting layer publishes **only** astronomer-facing artifacts. Raw
PRESTO intermediates stay internal. This document defines the policy.

## Two directory trees

| Tree | Purpose | Written by |
|------|---------|-----------|
| `runs/<run_id>/` | **Internal workdir.** Every PRESTO invocation writes its manifest, stdout/stderr and raw artifacts here. | the executor / PRESTO tools |
| `outputs/<run_id>/` | **Public modern artifacts.** Clean, reviewable outputs for an astronomer. | the reporting layer (`ArtifactManager`) |

`runs/` is raw and complete. `outputs/` is curated. The reporting layer treats
`runs/` as *read-only input* and never modifies a PRESTO run.

## Public output structure

```
outputs/<run_id>/
  manifest.json            inventory of this bundle (+ warnings/errors/log links)
  summary.json             observation + workflow + candidate summary
  candidates.csv           every parseable candidate, normalized
  report.html              offline scientific dashboard
  report.md                lightweight text report
  status.md                mirrored workflow status table
  timeline.json            mirrored workflow timeline
  visuals/*.png            collected / converted diagnostic plots
  thumbnails/*.png          small previews for the HTML report
  waterfalls/*.png|*.pdf   per-candidate waterfall diagnostics
  candidates/<id>/         per-candidate bundle (candidate.json, waterfall.*)
  assets/                  report assets
  presto_raw_exports/      raw PRESTO files — ONLY when explicitly requested
```

## Allowed vs forbidden public extensions

**Allowed by default:** `.json` `.csv` `.html` `.md` `.png` `.pdf`

**Forbidden by default (raw PRESTO):** `.dat` `.fft` `.inf` `.mask` `.sub*`
`.pfd` `.bestprof` `.singlepulse` `.singlepulse.gz` `.ps` `.eps` `.log` `.tmp`

`ArtifactManager.publish_file()` enforces the allowlist and refuses anything
else. `.ps` / `.eps` may be used as *internal conversion sources* (→ PNG) but
are never published.

**Exception — raw export.** When the user explicitly asks for original PRESTO
outputs, `ArtifactManager.publish_raw()` copies raw files into
`outputs/<run_id>/presto_raw_exports/`, clearly marked as raw, not modern.

## ArtifactPolicy

`ArtifactPolicy` is the per-bundle switch board:

```yaml
export_summary_json:            true
export_candidates_csv:          true
export_visual_png:              false
export_thumbnails:              false
export_waterfall_png:           false
export_waterfall_pdf:           false
export_report_html:             false
export_report_markdown:         false
export_original_presto_outputs: false
cleanup_intermediate_files:     true
max_candidates_for_waterfalls:  100
max_candidates_in_html:         500
default_waterfall_cmap:         inferno
```

## Intention routing

`generate_modern_report_bundle` does not parse prose. The LLM sets explicit
`wants_*` intention flags from the user request; `route_intention()` maps them
to an `ArtifactPolicy`:

| User intent | Flag | Effect |
|-------------|------|--------|
| Metadata only | `wants_metadata_only` | summary.json only |
| Candidate search | `wants_candidates` | summary.json + candidates.csv |
| Plots / visual inspection | `wants_visuals` | visuals + thumbnails + HTML |
| Waterfalls | `wants_waterfalls` | waterfall PNG + visuals + HTML |
| Waterfall PDFs | `wants_waterfall_pdf` | waterfall PDFs |
| Modern report / dashboard | `wants_report` | the full bundle |
| "do not create extra files" | `wants_no_extra_files` | nothing unless explicitly requested |
| Original PRESTO outputs | `wants_original_presto_outputs` | also `presto_raw_exports/` |

With no flag set, the bundle defaults to the full report.

## Guarantees

1. PRESTO workflows still run normally in `runs/`.
2. `outputs/` is clean, modern, astronomer-facing.
3. `candidates.csv` contains **all** parseable candidates, not only the best.
4. Raw PRESTO intermediates are never published by default.
5. PNGs / thumbnails / waterfall PDFs are produced only when requested or
   clearly implied.
6. Path traversal and accidental overwrites are rejected.
