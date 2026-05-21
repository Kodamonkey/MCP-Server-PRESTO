# Utility tools

This document covers only the **utility** tools (no PRESTO execution). For
the full list of PRESTO-binary tools (`presto.readfile`, `presto.rfifind`,
`presto.prepfold`, etc.) see the README.

Utility tools never run `docker`, never read artifact contents, never
shell out, and never write into `data/`.

## `presto.list_data_files`

| Input            | Type            | Default | Notes                                  |
|------------------|-----------------|---------|----------------------------------------|
| `limit`          | `int`           | 100     | 1–10000.                               |
| `extensions`     | `list[str]?`    | `null`  | e.g. `[".fil", ".fits"]`.              |
| `include_hidden` | `bool`          | `false` | Include dot-prefixed entries.          |

**Returns** `ListDataFilesResult`:

```json
{
  "data_dir_label": "data",
  "count": 3,
  "files": [
    {"relative_path": "obs1.fil", "size_bytes": 123456,
     "modified_at": "2026-05-16T14:30:52Z", "extension": ".fil",
     "likely_type": "filterbank"}
  ]
}
```

**Why an agent uses it.** Decide which file to feed `presto.readfile` /
`presto.rfifind` without guessing absolute paths.

## `presto.validate_environment`

| Input                    | Type   | Default | Notes                                          |
|--------------------------|--------|---------|------------------------------------------------|
| `check_image`            | `bool` | `true`  | If true, also `docker image inspect <image>`.  |
| `include_tool_readiness` | `bool` | `true`  | Probe the image for per-tool readiness.        |
| `force_refresh`          | `bool` | `false` | Bypass the ~15 min runtime-capability cache.   |

**Returns** `ValidateEnvironmentResult`:

```json
{
  "status": "WARN",
  "checks": [
    {"name": "settings.load", "status": "OK", "message": "..."},
    {"name": "tool_readiness.presto.rrattrap", "status": "ERROR",
     "message": "module.presto.singlepulse=ERROR",
     "remediation": "Use an image where presto.singlepulse imports cleanly."}
  ],
  "runtime_compatibility": {
    "image": "alex88ridolfi/presto5:png",
    "status": "ERROR",
    "capabilities": {"binaries": [], "python_modules": []},
    "tool_readiness": [
      {"tool_name": "rrattrap", "status": "ERROR", "blocking": true,
       "checks": []}
    ]
  }
}
```

Base checks: `settings.load`, `data_dir.exists`, `data_dir.has_files`,
`data_dir.zero_byte_files`, `runs.writable`, `outputs.writable`,
`logs.writable`, `docker.cli`, `docker.version`, `docker.image`,
`policy.defaults`. With `include_tool_readiness=true` it also runs lightweight
Docker probes and appends one `tool_readiness.presto.<tool>` check per tool
plus the structured `runtime_compatibility` block. Never raises; failed checks
become `ERROR` / `WARN` entries.

**Why an agent uses it.** Triage before launching expensive work. If
`docker.cli` is `ERROR`, no PRESTO tool will succeed; if a tool's readiness is
`ERROR`, skip it. See `RUNTIME_COMPATIBILITY.md`.

## `presto.summarize_run`

| Input    | Type   | Notes                                  |
|----------|--------|----------------------------------------|
| `run_id` | `str`  | Run id from `presto.list_runs`.        |

**Returns** `RunStructuredSummary`:

```json
{
  "run_id": "20260516T143052Z-K7QM3A",
  "tool": "rfifind",
  "status": "SUCCESS",
  "duration_s": 3.0,
  "exit_code": 0,
  "inputs": {"input_file": "obs.fil"},
  "artifact_counts": {"rfi": 1, "time_series": 2, "fft": 1},
  "artifacts_by_type": {"rfi": ["obs_rfifind.mask"], "...": []},
  "next_suggested_tools": ["presto.prepdata", "presto.single_pulse_search"],
  "notes": []
}
```

**Why an agent uses it.** Drive the next step without re-reading the
manifest plus walking the artifacts directory itself. Suggestions are a
hint, not an orchestration command — the agent decides.

## `presto.inspect_artifacts`

| Input    | Type   | Notes                                  |
|----------|--------|----------------------------------------|
| `run_id` | `str`  | Run id from `presto.list_runs`.        |

**Returns** `InspectArtifactsResult` — one row per artifact with `name`,
`size_bytes`, `modified_at`, `likely_type` (`ArtifactType`),
`resource_uri`, and `is_inline_readable` (true only for small text
artifacts: `.txt`, `.csv`, `.inf`, `.bestprof`, `.singlepulse`, `.tim`,
`.toa`, `.txtcand`, `.log`, `.json`).

**Why an agent uses it.** Decide which artifacts are worth fetching via
`presto://runs/{id}/artifacts/{filename}` and which to leave on disk.

---

# PRESTO tools (additional)

Beyond the canonical search pipeline already documented in the README, the
server exposes the following PRESTO routines. **Status** legend:
- `stable` — known good against mainline PRESTO; tested with `FakeDockerBackend`.
- `experimental` — wired and tested in isolation; awaiting verification against
  the configured Docker image. Tool description starts with `[experimental]`.
- `image-dependent` — correctness depends on image contents; readiness-gated
  via `runtime_checks` (fails fast with a controlled error if unavailable).
- `advanced` — production routine with a wide parameter space; conservative
  defaults shipped, broader knobs deliberately not exposed.
- `utility` — no Docker, no PRESTO execution (filesystem / parsing only).

Verify availability with `presto.validate_environment(include_tool_readiness=true)`
before relying on any non-`stable` tool.

### `presto.rrattrap` — experimental / image-dependent

Group `.singlepulse` detections into candidate groups (`groups.txt`) before
`make_spd`.

Requires:
- `rrattrap.py` in PATH inside the configured PRESTO image.
- Python module `presto.singlepulse` importable inside that image runtime.

Known issue:
Some PRESTO images include `rrattrap.py` but do not expose
`presto.singlepulse`. In that case `presto.rrattrap` fails fast with a
controlled error explaining this image/runtime mismatch.

## Data preparation

### `presto.psrfits2fil` — stable

Convert PSRFITS search-format to SIGPROC `.fil`.

| Input          | Type        | Notes                                 |
|----------------|-------------|---------------------------------------|
| `input_file`   | `str`       | Relative to `PRESTO_DATA_DIR`.        |
| `output_prefix`| `str?`      | Defaults to `"fil"`.                  |

**Returns** `Psrfits2FilResult { input_file, output_prefix, fil_files, inf_files, notes }`.

**PRESTO command:** `psrfits2fil.py -o <prefix> <input>`.

**Next tool:** `presto.readfile` on the produced `.fil`, then the standard
search pipeline.

### `presto.downsample_filterbank` — stable

Produce a factor-downsampled `.fil`.

| Input        | Type     | Notes                          |
|--------------|----------|--------------------------------|
| `input_file` | `str`    | Relative to `PRESTO_DATA_DIR`. |
| `factor`     | `int`    | `[2, 1024]`.                   |

**Returns** `DownsampleFilterbankResult { input_file, factor, output_file, notes }`.

**PRESTO command:** `downsample_filterbank.py <factor> <input>`.

**Next tool:** any downstream consumer of `.fil` (e.g. `presto.readfile`, `presto.rfifind`).

### `presto.fb_truncate` — stable

Cut a sample window from a filterbank (samples-mode).

| Input          | Type     | Notes                          |
|----------------|----------|--------------------------------|
| `input_file`   | `str`    | Relative to `PRESTO_DATA_DIR`. |
| `num_samples`  | `int`    | `[1, 10^10]`.                  |
| `start_sample` | `int`    | `[0, 10^12]`, default `0`.     |
| `output_prefix`| `str?`   | Defaults to `"trunc"`.         |

**Returns** `FbTruncateResult { input_file, output_file, output_prefix, start_sample, num_samples, notes }`.

**PRESTO command:** `fb_truncate.py -s <start> -n <num> -o <prefix> <input>`.

**Next tool:** the rest of the pipeline on the smaller `.fil` (debugging / fast
iteration).

## RFI mitigation

### `presto.rfifind_stats` — stable

Structured summary of a prior `rfifind` run.

| Input        | Type     | Notes                                                   |
|--------------|----------|---------------------------------------------------------|
| `stats_file` | `str`    | `<run_id>/artifacts/<file>.stats` under `RUNS_DIR`.     |
| `mask_file`  | `str?`   | Optional `<run_id>/artifacts/<file>.mask`.              |

**Returns** `RfifindStatsResult { stats_file, mask_file, summary_file, bad_channels, bad_intervals, notes }`.

**PRESTO command:** `rfifind_stats.py <stats> [<mask>]`.

**Next tool:** `presto.weights_to_ignorechan` for an ignorechan list, or
`presto.prepsubband` / `presto.prepdata` with the `.mask`.

### `presto.weights_to_ignorechan` — experimental

Convert `.weights` / `.mask` from a prior run into an ignorechan list.

| Input          | Type      | Notes                                                  |
|----------------|-----------|--------------------------------------------------------|
| `weights_file` | `str`     | `<run_id>/artifacts/<file>` under `RUNS_DIR`.          |
| `threshold`    | `float?`  | `[0.0, 1.0]`.                                          |

**Returns** `WeightsToIgnorechanResult { weights_file, ignorechan_file, ignore_channels, notes }`.

**PRESTO command:** `weights_to_ignorechan.py [-t <thr>] <weights>`.

### `presto.makezaplist` — experimental

Build a `.zaplist` from a `.birds` file.

| Input        | Type   | Notes                              |
|--------------|--------|------------------------------------|
| `input_file` | `str`  | Typically `.birds` under DATA_DIR. |

**Returns** `MakeZaplistResult { input_file, zaplist_file, notes }`.

**PRESTO command:** `makezaplist.py <input>`.

**Next tool:** `presto.zapbirds` with the resulting `.zaplist`.

## Fold QC

### `presto.pfd2png` — experimental

Render a `.pfd` to PNG/PS. Availability depends on the configured PRESTO image
(script is not part of every distribution).

| Input      | Type   | Notes                                              |
|------------|--------|----------------------------------------------------|
| `pfd_file` | `str`  | `<run_id>/artifacts/<file>.pfd` under `RUNS_DIR`.  |

**Returns** `Pfd2PngResult { pfd_file, png_file, ps_file, notes }`.

**PRESTO command:** `pfd2png.sh <pfd>`.

### `presto.pfdzap` — experimental

Apply strict interval/channel zapping to a `.pfd`.

| Input          | Type        | Notes                                               |
|----------------|-------------|-----------------------------------------------------|
| `pfd_file`     | `str`       | `<run_id>/artifacts/<file>.pfd` under `RUNS_DIR`.   |
| `zap_commands` | `list[str]` | Strict `<low>:<high>` tokens, max 512.              |
| `output_prefix`| `str?`      | Defaults to `"pfdzap"`.                             |

**Returns** `PfdZapResult { pfd_file, output_pfd_file, zap_commands_file, notes }`.

**PRESTO command:** `pfdzap.py -o <prefix> <zap_file> <pfd>`.

Arbitrary shell input is **rejected** by `policies.check_pfdzap_commands` —
each token must match `^\d+:\d+$`.

## Advanced periodic / candidate inspection

### `presto.fourier_fold` — experimental

Fold from `.fft` complex amplitudes at a known candidate.

| Input            | Type      | Notes                                                |
|------------------|-----------|------------------------------------------------------|
| `fft_file`       | `str`     | `<run_id>/artifacts/<file>.fft` under `RUNS_DIR`.    |
| `period_seconds` | `float?`  | OR `frequency_hz` — exactly one required.            |
| `frequency_hz`   | `float?`  | OR `period_seconds` — exactly one required.          |
| `dm`             | `float?`  | Optional DM `[0, 10000]`.                            |

**Returns** `FourierFoldResult { fft_file, profile_file, plot_file, summary, notes }`
where `summary: FourierFoldProfileSummary` mirrors the request parameters.

**PRESTO command:** `fourier_fold.py [-p <p> | -f <f>] [-dm <dm>] <fft>`.

### `presto.sum_profiles` — experimental

Combine many `.bestprof` / `.prof` files from prior runs.

| Input           | Type        | Notes                                              |
|-----------------|-------------|----------------------------------------------------|
| `profile_files` | `list[str]` | Each `<run_id>/artifacts/<file>`. Cap 4096.        |

**Returns** `SumProfilesResult { input_profile_files, output_profile_file, plot_file, notes }`.

**PRESTO command:** `sum_profiles.py <p1> <p2> ...`.

### `presto.search_bin` — advanced

Phase-modulation / sideband search for binary pulsars.

| Input      | Type      | Notes                                               |
|------------|-----------|-----------------------------------------------------|
| `fft_file` | `str`     | `<run_id>/artifacts/<file>.fft` under `RUNS_DIR`.   |
| `low_hz`   | `float?`  | Optional band, paired with `high_hz`.               |
| `high_hz`  | `float?`  | Optional band, paired with `low_hz`.                |

**Returns** `SearchBinResult { fft_file, candidate_files, top_candidates, notes }`
where `top_candidates: list[SearchBinCandidate]`.

**PRESTO command:** `search_bin [-flo <low> -fhi <high>] <fft>`.

## Stack search & birdie zapping

### `presto.stacksearch` — experimental / image-dependent

Stack-search several `.fft` files (each from a prior `realfft` run) to boost
weak periodic signals.

| Input       | Type        | Notes                                            |
|-------------|-------------|--------------------------------------------------|
| `fft_files` | `list[str]` | `<run_id>/artifacts/<file>.fft`, min 2, max 256. |

**Returns** `StackSearchResult { fft_files, candidate_files, summary_file, top_candidates, notes }`.

**PRESTO command:** `stacksearch.py <file1>.fft <file2>.fft ...` (run in `artifacts/`).

**Readiness:** needs `stacksearch.py` on PATH. A preflight fails fast with a
controlled error otherwise.

**Next tool:** `presto.sifting`, then `presto.prepfold` on survivors.

### `presto.simple_zapbirds` — experimental / image-dependent

Zap known interference ("birdies") out of one `.fft`. The source `.fft` is
**copied** into the new run's `artifacts/`; the zap runs on the copy — the
source is never modified in place.

| Input        | Type   | Notes                                                  |
|--------------|--------|--------------------------------------------------------|
| `fft_file`   | `str`  | `<run_id>/artifacts/<file>.fft` under `RUNS_DIR`.      |
| `birds_file` | `str`  | Birds/zap file: under `DATA_DIR` or a run artifact.    |

**Returns** `SimpleZapbirdsResult { input_fft_files, staged_fft_files, birds_file, zapped_fft_files, notes }`.

**PRESTO command:** `simple_zapbirds.py <staged>.fft <staged>.birds`.

**Readiness:** needs `simple_zapbirds.py` on PATH.

**Next tool:** `presto.accelsearch` on the zapped `.fft`.

## Known-pulsar cross-check (utility — no Docker)

### `presto.compare_periods` — utility

Compare a candidate spin period against pulsar ephemeris (`.par`) files and
their harmonics / subharmonics.

| Input          | Type        | Notes                                              |
|----------------|-------------|----------------------------------------------------|
| `period_ms`    | `float`     | Candidate spin period (ms).                        |
| `par_files`    | `list[str]` | `.par` files under `DATA_DIR` or run artifacts.    |
| `tolerance`    | `float?`    | Relative match tolerance (default `1e-3`).         |
| `max_harmonic` | `int?`      | Highest harmonic / subharmonic tested (default 8). |

**Returns** `ComparePeriodsResult { period_ms, par_files, tolerance, max_harmonic, matches, summary, notes }`
where each `PeriodMatch` carries `harmonic` (n>0 harmonic, n<0 subharmonic),
`delta` and a `confidence_label` (`exact` / `near` / `weak`).

Never asserts a detection — it reports how closely a candidate lines up with a
catalogued ephemeris.

### `presto.binary_info` — utility

Summarise the orbital parameters of a binary-pulsar `.par` file.

| Input      | Type     | Notes                                            |
|------------|----------|--------------------------------------------------|
| `par_file` | `str`    | `.par` under `DATA_DIR` or a run artifact.       |
| `inf_file` | `str?`   | Optional companion `.inf` (validated, recorded). |

**Returns** `BinaryInfoResult { par_file, inf_file, is_binary, pulsar_name, binary_summary, plot_files, notes }`.
`binary_summary` includes orbital period, projected semi-major axis,
eccentricity, the derived line-of-sight velocity amplitude and the
Doppler-smeared spin period / frequency range.

## Candidate review (utility — no Docker)

### `presto.compile_candidate_report_pdf` — utility

Bundle PNG/JPG plot artifacts from one or more runs into a single reviewable
PDF, written to a fresh `runs/<run_id>/artifacts/` directory.

| Input              | Type          | Notes                                          |
|--------------------|---------------|------------------------------------------------|
| `run_ids`          | `list[str]?`  | Runs whose `artifacts/` images to include.     |
| `artifact_paths`   | `list[str]?`  | Explicit `<run_id>/artifacts/<file>` images.   |
| `include_patterns` | `list[str]?`  | Globs; defaults to `*.png` / `*.jpg` / `*.jpeg`. |
| `title`            | `str?`        | Optional title page.                           |
| `output_prefix`    | `str?`        | PDF filename prefix (default `candidate_report`). |
| `sort_by`          | `enum`        | `run_id_name` (default) / `mtime` / `name`.    |

**Returns** `ToolRunResult[CandidateReportPdfResult]` — `pdf_file`,
`page_count`, `included_artifacts`, `skipped_artifacts`, `notes`,
`resource_uri`.

Reads **only** artifacts under `runs/` (never `data/`, never absolute paths).
Corrupt images are skipped (non-fatal if at least one valid image remains);
duplicate images (same content hash) are collapsed; page order is
deterministic.
