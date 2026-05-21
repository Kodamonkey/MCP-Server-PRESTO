# MCP prompts

Prompts in this server are **guidance text only**. They do not execute
pipelines. They tell the model/client which typed PRESTO tools to call, in
what order, and what to do with the results. Orchestration (looping,
branching, retries, candidate ranking) is the client's job — or a future
LangGraph layer above this MCP. The MCP layer ships atomic, sandboxed
capabilities and the prompts that describe how to compose them.

All prompts are registered via `@mcp.prompt(...)` and visible in MCP
Inspector under the same names.

## `presto.inspect_observation_plan`

| Input        | Type            | Notes                                    |
|--------------|-----------------|------------------------------------------|
| `input_file` | `str`           | Relative to `PRESTO_DATA_DIR`.           |
| `goal`       | `str` (opt)     | Free-form user intent (optional).        |

**When to use.** First contact with an unfamiliar observation file. You want
metadata (telescope, source, MJD, RA/DEC, freq, bw, channels, sample time,
duration) but no heavy search yet.

**Tools recommended.** `presto.readfile`, plus reads against
`presto://runs/<id>/{manifest,stdout,stderr}` if anything is unclear.

## `presto.single_pulse_search_plan`

| Input        | Type            | Notes                                    |
|--------------|-----------------|------------------------------------------|
| `input_file` | `str`           | Relative to `PRESTO_DATA_DIR`.           |
| `dm_low`     | `float` (opt)   | Lower bound of DM search.                |
| `dm_high`    | `float` (opt)   | Upper bound of DM search.                |
| `threshold`  | `float` (opt)   | Sigma cutoff for single-pulse detection. |

**When to use.** Looking for FRB-like / RRAT-like / giant-pulse events.

**Tools recommended.** `presto.validate_environment` →
`presto.readfile` → `presto.rfifind` → `presto.ddplan` →
`presto.prepsubband` (or `presto.prepdata`) → `presto.single_pulse_search` →
`presto.rrattrap` *(only if readiness OK)* → `presto.make_spd` →
`presto.plot_spd` → `presto.waterfaller` →
`presto.compile_candidate_report_pdf`.

The prompt now leads with `validate_environment`, gates `rrattrap` on tool
readiness, and carries the artifact / noise / candidate / detection taxonomy.

## `presto.periodic_search_plan`

| Input        | Type            | Notes                                    |
|--------------|-----------------|------------------------------------------|
| `input_file` | `str`           | Relative to `PRESTO_DATA_DIR`.           |
| `dm_low`     | `float` (opt)   | Lower bound of DM search.                |
| `dm_high`    | `float` (opt)   | Upper bound of DM search.                |
| `zmax`       | `int` (opt)     | Max Fourier acceleration.                |

**When to use.** Hunting an isolated or binary pulsar via Fourier /
acceleration search.

**Tools recommended.** `presto.validate_environment` →
`presto.readfile` → `presto.rfifind` → `presto.ddplan` →
`presto.prepdata`/`presto.prepsubband` → `presto.realfft` →
`presto.zapbirds` / `presto.simple_zapbirds` (optional) →
`presto.accelsearch` → `presto.sifting` → `presto.prepfold` →
`presto.get_toas` (optional) → `presto.compile_candidate_report_pdf`.

Guardrails: do not pass `accelsearch` `wmax` unless readiness confirms it; do
not fold without a traceable period; the FFT is never modified in place.

## `presto.fold_known_candidate_plan`

| Input            | Type     | Notes                                    |
|------------------|----------|------------------------------------------|
| `input_file`     | `str`    | Relative to `PRESTO_DATA_DIR`.           |
| `period_seconds` | `float`  | Candidate spin period (seconds).         |
| `dm`             | `float`  | Candidate DM (pc cm⁻³).                  |

**When to use.** You already have (P, DM); produce a folded profile and
optional TOAs.

**Tools recommended.** `presto.readfile`, optionally `presto.rfifind`,
`presto.prepfold`, optionally `presto.get_toas`.

## `presto.explain_failed_run`

| Input    | Type   | Notes                                    |
|----------|--------|------------------------------------------|
| `run_id` | `str`  | Run id from `presto.list_runs`.          |

**When to use.** A previous tool call failed; you want a structured triage.

**Tools recommended.** `presto.get_run_manifest`, reads against
`presto://runs/<id>/{stdout,stderr}`. The prompt classifies the failure
(path/input · docker/image · presto runtime · parser · timeout ·
memory/resource · missing artifact) and asks for one concrete next action.

## `presto.generate_candidate_report_plan`

| Input    | Type           | Notes                                            |
|----------|----------------|--------------------------------------------------|
| `run_id` | `str` (opt)    | If omitted, surveys recent runs.                 |

**When to use.** End-of-session summary of what was found and where the
evidence lives. Strictly distinguishes *artifact* / *noise* / *candidate* /
*detection*; refuses to assert scientific confirmation.

**Tools recommended.** `presto.list_runs`, `presto.get_run_manifest`,
`presto.summarize_run`.

## `presto.candidate_review_plan`

| Input    | Type           | Notes                                            |
|----------|----------------|--------------------------------------------------|
| `run_id` | `str` (opt)    | If omitted, surveys recent runs first.           |

**When to use.** An improved sibling of
`presto.generate_candidate_report_plan`: review existing run artifacts, add
known-pulsar cross-checks, and produce a bundled PDF.

**Tools recommended.** `presto.summarize_run` → `presto.inspect_artifacts` →
`presto.pfd2png` / `presto.waterfaller` → `presto.compare_periods` →
`presto.binary_info` → `presto.compile_candidate_report_pdf`.

Enforces the artifact / noise / candidate / detection taxonomy and explicitly
refuses to confirm a detection without human or external validation.

---

## `presto.prepare_filterbank_plan`

| Input        | Type          | Notes                                    |
|--------------|---------------|------------------------------------------|
| `input_file` | `str`         | Relative to `PRESTO_DATA_DIR`.           |
| `goal`       | `str` (opt)   | Free-form user goal.                     |

**When to use.** Data prep before any search. Decide format conversion,
truncation, or downsampling.

**Tools recommended.** `presto.readfile`, `presto.psrfits2fil`,
`presto.fb_truncate`, `presto.downsample_filterbank`.

## `presto.rfi_mitigation_plan`

| Input                       | Type        | Notes                              |
|-----------------------------|-------------|------------------------------------|
| `input_file`                | `str`       | Relative to `PRESTO_DATA_DIR`.     |
| `existing_rfifind_run_id`   | `str` (opt) | Skip step 1 if provided.           |

**When to use.** Before launching dedispersion or any search; or when a
search returns RFI-dominated results.

**Tools recommended.** `presto.rfifind`, `presto.rfifind_stats`,
`presto.weights_to_ignorechan`, `presto.makezaplist`, `presto.zapbirds`,
plus `.mask` consumers `presto.prepdata` / `presto.prepsubband`.

## `presto.fold_qc_plan`

| Input       | Type        | Notes                                        |
|-------------|-------------|----------------------------------------------|
| `pfd_file`  | `str`       | `<run_id>/artifacts/<file>.pfd`.             |
| `goal`      | `str` (opt) | Free-form (e.g. "rate this candidate").      |

**When to use.** Quality-check a folded candidate; decide whether to TOA,
zap, or sum.

**Tools recommended.** `presto.pfd2png`, `presto.pfdzap`,
`presto.get_toas`, `presto.sum_profiles`.

## `presto.periodic_advanced_search_plan`

| Input            | Type     | Notes                                       |
|------------------|----------|---------------------------------------------|
| `input_file`     | `str`    | Relative to `PRESTO_DATA_DIR`.              |
| `binary_search`  | `bool`   | If `true`, include `presto.search_bin`.     |

**When to use.** Full periodic search with optional binary-pulsar add-ons.

**Tools recommended.** Standard periodic pipeline plus `presto.fourier_fold`
(known candidate) and `presto.search_bin` (orbital sidebands).

## `presto.single_pulse_full_plan`

| Input       | Type            | Notes                                    |
|-------------|-----------------|------------------------------------------|
| `input_file`| `str`           | Relative to `PRESTO_DATA_DIR`.           |
| `dm_low`    | `float` (opt)   | DM band lower bound.                     |
| `dm_high`   | `float` (opt)   | DM band upper bound.                     |

**When to use.** End-to-end single-pulse pipeline including RFI summary +
debugging hint via `presto.fb_truncate`.

**Tools recommended.** `presto.readfile`, `presto.rfifind`,
`presto.rfifind_stats`, `presto.ddplan`, `presto.prepsubband`,
`presto.single_pulse_search`, `presto.rrattrap`, `presto.make_spd`,
`presto.plot_spd`, `presto.waterfaller`, `presto.fb_truncate`.

## `presto.tool_selection_guide`

| Input  | Type   | Notes                       |
|--------|--------|-----------------------------|
| `task` | `str`  | Free-form task description. |

**When to use.** Agent needs to decide which tool to call given a task it
hasn't seen before.

**Returns.** Categorized index across data prep / RFI / dedispersion /
periodic / single-pulse / folding / timing / visualization / debugging /
advanced. Experimental tools are flagged inline.

---

**Reminder.** Every prompt ends with the disclaimer:

> NOTE: This prompt is guidance only. The MCP server does NOT auto-execute
> this plan. The model/client is responsible for issuing the typed tool
> calls listed below in the order it deems appropriate. A future LangGraph
> (or equivalent) orchestrator may drive these steps adaptively; this MCP
> layer ships atomic, sandboxed capabilities and never invents results.
