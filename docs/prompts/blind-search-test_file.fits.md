/anthropic-skills:caveman

Analyze `data/test_file.fits` as an **unknown** radio-astronomy observation (blind search).

**Do NOT assume** source name, period, DM, sky target, or signal type.

---

## STRICT CONSTRAINTS

- Use **ONLY** MCP/PRESTO tools (`presto.*`).
- **NO** custom scripts, external tools, or manual file creation.
- **NO** artifacts outside what MCP tools produce.
- Allowed trees: `runs/<run_id>/` (raw PRESTO) and `outputs/<run_id>/` (modern bundle).

---

## GOAL (critical)

Find **plausible astrophysical events**, **NOT** RFI at DM≈0.

- Treat **DM < 5 pc/cm³** as *likely RFI/noise* unless strong counter-evidence.
- Prioritize candidates with **DM ≥ 5**, dedispersed bow-tie morphology, or periodic/acceleration detections.
- Do **NOT** claim discovery; separate: high-confidence astro / low-confidence / likely RFI.

---

## REQUIRED WORKFLOW (call tools in this order)

### 0) Environment

1. `presto.validate_environment` (`check_image=true`, `include_tool_readiness=true`)

### 1) Inspect data

2. `presto.readfile` on `test_file.fits`
3. `presto.list_data_files` if needed

### 2) RFI + search plan

4. `presto.rfifind` on `test_file.fits` (keep mask path for later)
5. `presto.ddplan` with DM range appropriate for blind search (e.g. 0–500 pc/cm³), using `test_file.fits`
6. `presto.prepsubband` over a **wide DM grid** (many trials, not only DM 0–10)
7. `presto.prepdata` at representative high-DM trials if useful for FFT chain
8. `presto.realfft` on **multiple** dedispersed `.dat` files (several DM trials, including ~30–50 pc/cm³ if in grid)
9. `presto.accelsearch` on those FFTs (periodic/binary candidates)
10. `presto.single_pulse_search` on dedispersed data (broad DM coverage)

> **Forbidden shortcut:** do NOT conclude “no pulsar/FRB” from searches only at DM 0, 5, 10.

### 3) Modern reporting bundle (ONE final bundle — mandatory)

11. **`presto.generate_modern_report_bundle`** with **ALL** relevant `run_ids` from steps above:

```
input_file = test_file.fits
wants_report = true
wants_visuals = true
wants_waterfalls = true
wants_waterfall_pdf = true
waterfall_cmap = inferno
waterfall_selection = top_n
waterfall_top_n = 20
title = "Blind search — test_file.fits"
```

**Must produce under a single `outputs/<run_id>/`:**

- `report.html` (with links/images to waterfalls + visuals)
- `summary.json`
- `candidates.csv`
- `visuals/*.png` + `thumbnails/*.png`
- `waterfalls/*.png` (+ `.pdf` if enabled)
- `candidates/<id>/waterfall.png`
- `manifest.json`

### 4) Extra visuals from PRESTO plots (if `.ps`/`.png` exist in runs)

12. If steps produced plots only under `runs/*/artifacts/`, call:

    - `presto.generate_visual_artifacts` with the same `run_ids`
    - Then ensure final `report.html` includes those visuals (re-bundle if needed).

### 5) Waterfalls — anti-RFI selection (mandatory)

Exclude DM=0 RFI spikes when rendering waterfalls:

- Use `presto.generate_candidate_waterfalls` with:

  - `input_file = test_file.fits`
  - `min_dm = 5.0`
  - `min_snr = 6.0`
  - `color_map = inferno`
  - `export_png = true`, `export_pdf = true`
  - `time_window_sec = 0.5` to `2.0`
  - same `run_ids` as search steps

For top astro candidates, optionally also `presto.waterfaller` per event with:

- `mask_file` from rfifind mask when available
- candidate `time_sec`, `dm`, `duration_s` ≈ 1–2 s

### 6) PDF compilation (only via MCP)

13. `presto.compile_candidate_report_pdf` only if PNGs exist under `runs/*/artifacts/`:

    - Include all waterfaller `run_ids` (each has `runs/<id>/artifacts/waterfall.png`)
    - Include search `run_ids` with PNG diagnostics
    - `include_patterns`: `["waterfall*.png", "*.png"]`
    - If no PNG in `runs/`, report PDF as **not produced** (do not fake it)

> `compile_candidate_report_pdf` reads **`runs/`**, not `outputs/`.

---

## DELIVERABLES

1. Observation metadata summary
2. MCP tools/steps executed (with `run_id`s)
3. Candidate table: ID, type, DM, SNR, time, confidence, artifact paths (`outputs/` and `runs/`)
4. Path to `outputs/<bundle_run_id>/report.html`
5. Confirm folders: `visuals/`, `waterfalls/`, `candidates/`
6. Path to MCP-generated PDF if produced
7. Evidence for/against astrophysical origin
8. Final conclusion (conservative)

---

## VERIFICATION (must confirm before finishing)

- [ ] `report.html` exists and links to `waterfalls/*.png`
- [ ] At least one PNG in `outputs/.../waterfalls/`
- [ ] Waterfalls used `min_dm ≥ 5`
- [ ] Search spanned many DM trials (not only DM 0–10)
- [ ] No manual files; all paths are real MCP outputs
