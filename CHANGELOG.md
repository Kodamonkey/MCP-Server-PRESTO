# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/) and the project aims to follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- **Runtime capability subsystem** (`src/presto_mcp/runtime_checks.py`):
  lightweight, cached Docker probes (`which`, `python3 -c import`, `-h`) that
  turn image gaps into structured readiness data. New Pydantic models
  `RuntimeCheck`, `PrestoRuntimeCapabilities`, `ToolReadiness`,
  `RuntimeCompatibilityResult`.
- `presto.validate_environment` now accepts `include_tool_readiness` and
  `force_refresh` and reports per-tool readiness in `runtime_compatibility`.
- **New tools:**
  - `presto.stacksearch` — stack search over multiple `.fft` files
    (experimental / image-dependent).
  - `presto.simple_zapbirds` — Fourier birdie zapping; stages a copy so the
    source `.fft` is never modified in place (experimental / image-dependent).
  - `presto.compare_periods` — no-Docker utility: cross-check a candidate
    period against `.par` ephemerides and their harmonics / subharmonics.
  - `presto.binary_info` — no-Docker utility: orbital summary + Doppler period
    range from a binary-pulsar `.par` file.
  - `presto.compile_candidate_report_pdf` — no-Docker utility: bundle run plot
    artifacts into one reviewable PDF (Pillow).
- New MCP prompt `presto.candidate_review_plan` — readiness-gated candidate
  review with an explicit artifact / noise / candidate / detection taxonomy.
- New docs: `RUNTIME_COMPATIBILITY.md`, `CONTRIBUTING.md`, `CHANGELOG.md`,
  `CITATION.cff`, a PRESTO-tool-bug issue template.
- New `workflow_dispatch` CI workflow `runtime-compatibility.yml` that probes
  the PRESTO image and uploads `runtime_compatibility.json` + `tool_readiness.md`.

### Changed

- `presto.rrattrap` preflight refactored to use the shared `runtime_checks`
  module instead of an ad-hoc probe; the controlled error still names
  `presto.singlepulse`, `rrattrap.py` and `validate_environment`.
- `presto.ddplan` gained `input_file` (raw filterbank/PSRFITS appended as a
  positional argument so DDplan.py infers obs params), `write_dedisp_script`
  (`-w`, capability-gated, requires `input_file`) and `output_prefix`. The
  parametric mode is unchanged; obs params are now optional when `input_file`
  is supplied.
- `presto.accelsearch` gained capability-aware `wmax` (jerk search), `sigma`,
  `ncpus` and a parser-only `candidate_limit`. Advanced flags are checked
  against `accelsearch -h`; an unsupported flag raises a clear error.
- Search-plan prompts (`single_pulse_search_plan`, `periodic_search_plan`,
  `tool_selection_guide`) now lead with `validate_environment`, gate
  experimental tools on readiness, and carry the evidence taxonomy.
- `Pillow` added as a runtime dependency (PDF assembly).

### Notes

- No new Docker image, no LangGraph, no generic shell tool, no `docker.sock`
  mount. Existing tool / prompt / model names remain backward compatible.

[Unreleased]: https://github.com/Kodamonkey/MCP-Server-PRESTO
