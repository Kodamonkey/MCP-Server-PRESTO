"""MCP prompt builders.

Pure text builders. No I/O, no Docker, no PRESTO execution. They produce
guidance strings that the MCP client / model uses to drive subsequent typed
tool calls. Orchestration is the client's job (or a future LangGraph layer);
this server only ships atomic capabilities and the guidance for using them.
"""

from __future__ import annotations

DISCLAIMER = (
    "NOTE: This prompt is guidance only. The MCP server does NOT auto-execute "
    "this plan. The model/client is responsible for issuing the typed tool "
    "calls listed below in the order it deems appropriate. A future LangGraph "
    "(or equivalent) orchestrator may drive these steps adaptively; this MCP "
    "layer ships atomic, sandboxed capabilities and never invents results."
)


def _fmt_opt(label: str, value: object | None) -> str:
    return f"{label}={value}" if value is not None else f"{label}=<unset>"


def build_inspect_observation_plan(input_file: str, goal: str | None = None) -> str:
    goal_line = f"User goal: {goal}" if goal else "User goal: not provided."
    return (
        f"# Inspect observation plan\n\n"
        f"Target file (relative to DATA_DIR): {input_file}\n"
        f"{goal_line}\n\n"
        f"Steps:\n"
        f"1. Call `presto.readfile` with input_file={input_file!r}.\n"
        f"2. From the structured result, extract and report:\n"
        f"   - file_format, telescope, source_name\n"
        f"   - mjd_start, ra, dec\n"
        f"   - central_freq_mhz, total_bandwidth_mhz, num_channels\n"
        f"   - sample_time_us, duration_s, bits_per_sample\n"
        f"3. If any field is missing or unclear, read:\n"
        f"   - `presto://runs/<run_id>/manifest`\n"
        f"   - `presto://runs/<run_id>/stdout`\n"
        f"   - `presto://runs/<run_id>/stderr`\n"
        f"4. Produce a short technical summary of the observation. Do NOT\n"
        f"   launch any heavy search (rfifind/prepsubband/accelsearch/etc.)\n"
        f"   in this step.\n\n"
        f"{DISCLAIMER}\n"
    )


def build_single_pulse_search_plan(
    input_file: str,
    dm_low: float | None = None,
    dm_high: float | None = None,
    threshold: float | None = None,
) -> str:
    return (
        f"# Single-pulse search plan\n\n"
        f"Target: {input_file}\n"
        f"Params: {_fmt_opt('dm_low', dm_low)}, {_fmt_opt('dm_high', dm_high)}, "
        f"{_fmt_opt('threshold', threshold)}\n\n"
        f"Conceptual pipeline (issue as discrete tool calls):\n"
        f"1. `presto.readfile` — confirm metadata (freq, bw, channels, sample time, duration).\n"
        f"2. `presto.rfifind` — produce a .mask for the observation.\n"
        f"3. `presto.ddplan` — derive an optimal DM-trial plan from the metadata\n"
        f"   and the dm_low/dm_high range supplied by the user.\n"
        f"4. `presto.prepsubband` (preferred) or `presto.prepdata` per DM trial\n"
        f"   using the .mask from step 2.\n"
        f"5. `presto.single_pulse_search` on the resulting .dat files\n"
        f"   (threshold={_fmt_opt('threshold', threshold)}).\n"
        f"6. `presto.rrattrap` to group .singlepulse events.\n"
        f"7. `presto.make_spd` to produce single-pulse diagnostic .spd files.\n"
        f"8. `presto.plot_spd` to render diagnostic PNGs.\n"
        f"9. For interesting candidates, `presto.waterfaller` around the event\n"
        f"   (start_s, duration_s, dm).\n\n"
        f"Rules:\n"
        f"- Do NOT invent candidates if no artifacts exist; report 'no detections'.\n"
        f"- Each step writes its own run with manifest + stdout + stderr URIs;\n"
        f"  chain by passing `<run_id>/artifacts/<file>` to the next tool.\n\n"
        f"{DISCLAIMER}\n"
    )


def build_periodic_search_plan(
    input_file: str,
    dm_low: float | None = None,
    dm_high: float | None = None,
    zmax: int | None = None,
) -> str:
    return (
        f"# Periodic (Fourier/acceleration) search plan\n\n"
        f"Target: {input_file}\n"
        f"Params: {_fmt_opt('dm_low', dm_low)}, {_fmt_opt('dm_high', dm_high)}, "
        f"{_fmt_opt('zmax', zmax)}\n\n"
        f"Conceptual pipeline:\n"
        f"1. `presto.readfile` — confirm metadata.\n"
        f"2. `presto.rfifind` — produce a .mask.\n"
        f"3. `presto.ddplan` — derive DM trials from the metadata + dm_low/dm_high.\n"
        f"4. `presto.prepdata` (single trial) or `presto.prepsubband` (range) using\n"
        f"   the .mask from step 2.\n"
        f"5. `presto.realfft` on each .dat to produce .fft.\n"
        f"6. Optional: `presto.zapbirds` to apply a known-birds zaplist to the .fft.\n"
        f"7. `presto.accelsearch` on each .fft (zmax={_fmt_opt('zmax', zmax)}).\n"
        f"8. `presto.sifting` across all ACCEL_* candidate files to dedupe/rank.\n"
        f"9. `presto.prepfold` on top surviving candidates (period + DM).\n"
        f"10. Optional: `presto.get_toas` if a folded .pfd + template is available.\n\n"
        f"Rules:\n"
        f"- Do NOT report a detection from a single DM trial; require sifting\n"
        f"  survivors and a clean folded profile.\n"
        f"- Cite artifact URIs (`presto://runs/<id>/artifacts/...`) when reporting.\n\n"
        f"{DISCLAIMER}\n"
    )


def build_fold_known_candidate_plan(
    input_file: str, period_seconds: float, dm: float
) -> str:
    return (
        f"# Fold a known candidate\n\n"
        f"Target: {input_file}\n"
        f"Known period_seconds={period_seconds}, dm={dm}.\n\n"
        f"Steps:\n"
        f"1. `presto.readfile` — confirm the file is readable and gather metadata.\n"
        f"2. Optional: `presto.rfifind` if no .mask exists for this observation.\n"
        f"3. `presto.prepfold` with period_seconds={period_seconds}, dm={dm}.\n"
        f"4. Inspect the resulting .pfd, .bestprof, and .pfd.ps/.pfd.png artifacts\n"
        f"   via `presto://runs/<run_id>/artifacts/...`.\n"
        f"5. If a Gaussian template exists under DATA_DIR, optionally call\n"
        f"   `presto.get_toas` with pfd_file=`<run_id>/artifacts/<file>.pfd`\n"
        f"   and template_file=<template under DATA_DIR>.\n\n"
        f"{DISCLAIMER}\n"
    )


def build_explain_failed_run(run_id: str) -> str:
    return (
        f"# Explain failed run\n\n"
        f"run_id: {run_id}\n\n"
        f"Steps:\n"
        f"1. Call `presto.get_run_manifest` with run_id={run_id!r}; note `status`,\n"
        f"   `exit_code`, `error`, `docker_argv`, `presto_argv`, `duration_s`,\n"
        f"   `timeout_s`, `cpus`, `memory_mb`.\n"
        f"2. Read `presto://runs/{run_id}/stderr` and then `presto://runs/{run_id}/stdout`.\n"
        f"3. Classify the failure into ONE of:\n"
        f"   - path/input        — PathSecurityError / file not found / .mask missing\n"
        f"   - docker/image      — DockerInvocationError / image pull / daemon down\n"
        f"   - presto runtime    — non-zero exit from the PRESTO binary itself\n"
        f"   - parser            — ParserError reading PRESTO stdout\n"
        f"   - timeout           — status=TIMEOUT, duration ≥ timeout_s\n"
        f"   - memory/resource   — OOM kill / cpu cap / pids cap exceeded\n"
        f"   - missing artifact  — exit 0 but expected artifact absent\n"
        f"4. Recommend ONE concrete next action (e.g. 'reduce zmax to 100',\n"
        f"   'rerun with PRESTO_DEFAULT_TIMEOUT_SECONDS=3600', 'pull image').\n"
        f"5. Do NOT speculate beyond what the manifest and logs show.\n\n"
        f"{DISCLAIMER}\n"
    )


def build_generate_candidate_report_plan(run_id: str | None = None) -> str:
    target_line = (
        f"Focus run_id: {run_id}"
        if run_id
        else "No run_id supplied — survey all recent runs."
    )
    return (
        f"# Candidate report plan\n\n"
        f"{target_line}\n\n"
        f"Steps:\n"
        f"1. If no run_id was supplied, call `presto.list_runs` (limit ~20).\n"
        f"2. For each relevant run, call `presto.get_run_manifest` and\n"
        f"   `presto.summarize_run` to get artifact groupings.\n"
        f"3. Identify artifacts of these kinds:\n"
        f"   - `.singlepulse`       — single-pulse events\n"
        f"   - `.spd`               — single-pulse diagnostics\n"
        f"   - `ACCEL_*`, `.txtcand`— acceleration-search candidates\n"
        f"   - `.pfd`, `.bestprof`  — folded profiles\n"
        f"   - `.png`, `.ps`, `.pdf`— diagnostic plots\n"
        f"4. Summarize the evidence per candidate. Strictly distinguish:\n"
        f"   - artifact (file on disk, no claim)\n"
        f"   - noise / RFI\n"
        f"   - candidate (passes sifting / SNR threshold)\n"
        f"   - detection (multi-DM, multi-pass, clean folded profile)\n"
        f"5. Do NOT assert a scientific confirmation; report what the artifacts show.\n\n"
        f"{DISCLAIMER}\n"
    )


def build_prepare_filterbank_plan(input_file: str, goal: str | None = None) -> str:
    goal_line = f"User goal: {goal}" if goal else "User goal: not provided."
    return (
        f"# Filterbank data-preparation plan\n\n"
        f"Target: {input_file}\n"
        f"{goal_line}\n\n"
        f"Steps:\n"
        f"1. Call `presto.readfile` to confirm format + metadata.\n"
        f"2. If the file is PSRFITS search-format and downstream tools require\n"
        f"   SIGPROC `.fil`, call `presto.psrfits2fil`. The output `.fil` lives\n"
        f"   in `runs/<run_id>/artifacts/` — reference it as\n"
        f"   `<run_id>/artifacts/<file>.fil` for chained tools.\n"
        f"3. If the file is very large and the goal is debugging or rapid\n"
        f"   iteration, call `presto.fb_truncate` with `start_sample`/\n"
        f"   `num_samples` to produce a small window.\n"
        f"4. If a lighter representation suffices (e.g. quick visual check),\n"
        f"   call `presto.downsample_filterbank` with a factor in [2, 1024].\n"
        f"5. Do NOT launch any search (rfifind/prepsubband/accelsearch/etc.)\n"
        f"   yet. This prompt is preparation only.\n\n"
        f"{DISCLAIMER}\n"
    )


def build_rfi_mitigation_plan(
    input_file: str, existing_rfifind_run_id: str | None = None
) -> str:
    head = (
        f"Reuse rfifind from run_id={existing_rfifind_run_id}."
        if existing_rfifind_run_id
        else "No existing rfifind run; one must be produced first."
    )
    return (
        f"# RFI mitigation plan\n\n"
        f"Target: {input_file}\n"
        f"{head}\n\n"
        f"Steps:\n"
        f"1. If no rfifind run exists, call `presto.rfifind` to generate\n"
        f"   `.mask`, `.rfi`, `.stats`, `.bytemask`.\n"
        f"2. Call `presto.rfifind_stats` on `<run_id>/artifacts/<file>.stats`\n"
        f"   (and optionally the `.mask`) for structured bad_channels /\n"
        f"   bad_intervals.\n"
        f"3. If a `.weights`/`.mask` exists, call\n"
        f"   `presto.weights_to_ignorechan` to convert to an ignorechan list.\n"
        f"4. For known periodic RFI (a `.birds` file under DATA_DIR), call\n"
        f"   `presto.makezaplist` to build a `.zaplist`.\n"
        f"5. Apply the zaplist to a `.fft` with `presto.zapbirds`.\n\n"
        f"When to use what:\n"
        f"- `.mask`: used by `presto.prepdata` / `presto.prepsubband` for\n"
        f"  dedispersion-time masking.\n"
        f"- `.zaplist`: used by `presto.zapbirds` for Fourier-domain zapping\n"
        f"  before `presto.accelsearch`.\n"
        f"- ignorechan list: passed to tools that accept channel-skip lists.\n\n"
        f"Note: `presto.rfifind_stats`, `presto.weights_to_ignorechan`,\n"
        f"`presto.makezaplist` are experimental — verify availability with\n"
        f"`presto.validate_environment` before relying on them.\n\n"
        f"{DISCLAIMER}\n"
    )


def build_fold_qc_plan(pfd_file: str, goal: str | None = None) -> str:
    goal_line = f"Goal: {goal}" if goal else "Goal: general fold QC."
    return (
        f"# Fold QC plan\n\n"
        f"Target .pfd: {pfd_file}\n"
        f"{goal_line}\n\n"
        f"Steps:\n"
        f"1. Read `presto://runs/<run_id>/artifacts/<file>.bestprof` and\n"
        f"   `.ps`/`.png` to inspect profile quality.\n"
        f"2. If no PNG exists and you want one, call `presto.pfd2png`\n"
        f"   (experimental — verify availability first).\n"
        f"3. If you have a Gaussian template under DATA_DIR, or can use a\n"
        f"   simple Gaussian width, call `presto.get_toas` for TOA generation.\n"
        f"4. To combine multiple folds, call `presto.sum_profiles`\n"
        f"   (experimental).\n\n"
        f"Do NOT make scientific claims (detection / confirmation) without\n"
        f"the artifact evidence on disk.\n\n"
        f"{DISCLAIMER}\n"
    )


def build_periodic_advanced_search_plan(
    input_file: str, binary_search: bool = False
) -> str:
    return (
        f"# Periodic / advanced search plan\n\n"
        f"Target: {input_file}\n"
        f"binary_search={binary_search}\n\n"
        f"Base pipeline (see also `presto.periodic_search_plan`):\n"
        f"1. `presto.readfile`\n"
        f"2. `presto.rfifind`\n"
        f"3. `presto.ddplan`\n"
        f"4. `presto.prepsubband` (preferred) or `presto.prepdata`\n"
        f"5. `presto.realfft`\n"
        f"6. Optional: `presto.zapbirds` with a `.zaplist`\n"
        f"7. `presto.accelsearch`\n"
        f"8. `presto.sifting`\n"
        f"9. `presto.prepfold` on top survivors\n\n"
        f"Advanced add-ons:\n"
        f"- If `binary_search=True`, run `presto.search_bin` on each `.fft`\n"
        f"  to look for orbital sidebands (advanced).\n\n"
        f"{DISCLAIMER}\n"
    )


def build_single_pulse_full_plan(
    input_file: str,
    dm_low: float | None = None,
    dm_high: float | None = None,
) -> str:
    dm_line = (
        f"DM band: [{dm_low}, {dm_high}]"
        if dm_low is not None and dm_high is not None
        else "DM band: not provided (set both dm_low and dm_high before ddplan)."
    )
    return (
        f"# Full single-pulse pipeline plan\n\n"
        f"Target: {input_file}\n"
        f"{dm_line}\n\n"
        f"Steps:\n"
        f"1. `presto.readfile` — confirm metadata.\n"
        f"2. `presto.rfifind` — produce `.mask`/`.stats`.\n"
        f"3. `presto.rfifind_stats` — structured bad_channels/bad_intervals\n"
        f"   (experimental).\n"
        f"4. `presto.ddplan` — derive DM trials from metadata + DM band.\n"
        f"5. `presto.prepsubband` — dedisperse the DM range using the `.mask`.\n"
        f"6. `presto.single_pulse_search` — detect pulses on each `.dat`.\n"
        f"7. `presto.rrattrap` — group events.\n"
        f"8. `presto.make_spd` — single-pulse diagnostic `.spd` files.\n"
        f"9. `presto.plot_spd` — render PNGs.\n"
        f"10. `presto.waterfaller` — per-candidate dynamic spectrum.\n\n"
        f"Debugging:\n"
        f"- If the input is too large for fast iteration, call\n"
        f"  `presto.fb_truncate` first and run the pipeline on the subset.\n\n"
        f"{DISCLAIMER}\n"
    )


def build_tool_selection_guide(task: str) -> str:
    return (
        f"# Tool selection guide\n\n"
        f"Task: {task}\n\n"
        f"Map the user's task to the right typed tool(s):\n\n"
        f"- **Data preparation / inspection**: `presto.readfile`,\n"
        f"  `presto.list_data_files`, `presto.psrfits2fil`,\n"
        f"  `presto.fb_truncate`, `presto.downsample_filterbank`.\n"
        f"- **RFI mitigation**: `presto.rfifind`, `presto.rfifind_stats`\n"
        f"  (experimental), `presto.weights_to_ignorechan` (experimental),\n"
        f"  `presto.makezaplist` (experimental), `presto.zapbirds`.\n"
        f"- **Dedispersion**: `presto.ddplan`, `presto.prepdata`,\n"
        f"  `presto.prepsubband`.\n"
        f"- **Periodic search**: `presto.realfft`, `presto.accelsearch`,\n"
        f"  `presto.sifting`, `presto.prepfold`.\n"
        f"- **Single-pulse search**: `presto.single_pulse_search`,\n"
        f"  `presto.rrattrap`, `presto.make_spd`, `presto.plot_spd`.\n"
        f"- **Folding / candidate inspection**: `presto.prepfold`,\n"
        f"  `presto.pfd2png` (experimental), `presto.sum_profiles`\n"
        f"  (experimental).\n"
        f"- **Timing**: `presto.get_toas`.\n"
        f"- **Visualization**: `presto.waterfaller`, `presto.plot_spd`,\n"
        f"  `presto.pfd2png` (experimental).\n"
        f"- **Debugging / triage**: `presto.list_runs`,\n"
        f"  `presto.get_run_manifest`, `presto.summarize_run`,\n"
        f"  `presto.inspect_artifacts`, `presto.validate_environment`,\n"
        f"  `presto.explain_failed_run` (prompt).\n"
        f"- **Advanced binary search**: `presto.search_bin` (advanced).\n\n"
        f"Always prefer running `presto.validate_environment` before relying\n"
        f"on an experimental tool. Use `presto.list_runs` /\n"
        f"`presto.get_run_manifest` to chain artifacts across runs.\n\n"
        f"{DISCLAIMER}\n"
    )


__all__ = [
    "DISCLAIMER",
    "build_explain_failed_run",
    "build_fold_known_candidate_plan",
    "build_fold_qc_plan",
    "build_generate_candidate_report_plan",
    "build_inspect_observation_plan",
    "build_periodic_advanced_search_plan",
    "build_periodic_search_plan",
    "build_prepare_filterbank_plan",
    "build_rfi_mitigation_plan",
    "build_single_pulse_full_plan",
    "build_single_pulse_search_plan",
    "build_tool_selection_guide",
]
