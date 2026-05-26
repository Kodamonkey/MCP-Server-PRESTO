"""Pydantic v2 schemas shared across the server.

Models split into three groups:

  * **Wire / API**: ``ToolRunResult`` and friends — what tools return to MCP.
  * **Manifest**: ``RunManifest`` and ``DockerInvocation`` — persisted JSON.
  * **Tool-specific**: ``ReadfileMetadata``, ``RfifindSummary``, ``PrepfoldResult``.

``Generic[T]`` is used for ``ToolRunResult`` so MCP clients see the correct
result type per tool when ``structuredContent`` is serialized.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field


class RunStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"


class DockerInvocation(BaseModel):
    """Everything needed to invoke a container deterministically."""

    model_config = ConfigDict(frozen=True)

    image: str
    container_name: str
    argv: list[str]  # full docker argv including 'docker' and the trailing command
    cpus: float
    memory_mb: int
    pids_limit: int = 256
    network: Literal["none"] = "none"


class RunManifest(BaseModel):
    """On-disk manifest persisted at ``runs/<run_id>/manifest.json``."""

    schema_version: Literal[1] = 1

    run_id: str
    tool: str
    status: RunStatus
    exit_code: int | None = None

    started_at: datetime
    finished_at: datetime | None = None
    duration_s: float | None = None
    timeout_s: int

    image: str
    image_digest: str | None = None

    docker_argv: list[str]
    presto_argv: list[str]

    inputs: dict[str, str] = Field(default_factory=dict)
    container_inputs: dict[str, str] = Field(default_factory=dict)

    cpus: float
    memory_mb: int

    stdout_path: str = "stdout.log"
    stderr_path: str = "stderr.log"
    artifacts: list[str] = Field(default_factory=list)

    error: str | None = None


# -- Tool-specific result schemas -----------------------------------------------


class ReadfileMetadata(BaseModel):
    file_format: str | None = None
    telescope: str | None = None
    source_name: str | None = None
    mjd_start: float | None = None
    ra: str | None = None
    dec: str | None = None
    sample_time_us: float | None = None
    central_freq_mhz: float | None = None
    low_channel_mhz: float | None = None
    high_channel_mhz: float | None = None
    channel_width_mhz: float | None = None
    num_channels: int | None = None
    total_bandwidth_mhz: float | None = None
    duration_s: float | None = None
    bits_per_sample: int | None = None
    raw_fields: dict[str, str] = Field(default_factory=dict)


class RfifindSummary(BaseModel):
    mask_file: str | None = None
    rfi_file: str | None = None
    stats_file: str | None = None
    ps_file: str | None = None
    time_s: float
    num_channels: int | None = None
    sample_time: float | None = None
    num_intervals: int | None = None
    good_intervals: int | None = None
    bad_intervals: int | None = None
    rfi_instances: int | None = None
    pct_masked: float | None = None


class PrepfoldResult(BaseModel):
    period_s: float
    dm: float
    output_prefix: str
    pfd_file: str | None = None
    ps_file: str | None = None
    bestprof_file: str | None = None
    png_file: str | None = None


class PrepdataResult(BaseModel):
    dm: float
    output_prefix: str
    dat_file: str | None = None
    inf_file: str | None = None
    num_samples: int | None = None
    sample_time_s: float | None = None


class DDplanPass(BaseModel):
    low_dm: float
    dm_step: float
    dms_per_call: int
    num_calls: int
    downsamp: int


class DDplanResult(BaseModel):
    dm_low: float
    dm_high: float
    num_dms: int
    # Observation params are None in input_file mode (DDplan derives them from
    # the raw file) unless the caller also passed them explicitly.
    freq_mhz: float | None = None
    bw_mhz: float | None = None
    num_channels: int | None = None
    sample_time_us: float | None = None
    input_file: str | None = None
    passes: list[DDplanPass] = Field(default_factory=list)
    plot_file: str | None = None
    dedisp_script: str | None = None
    notes: list[str] = Field(default_factory=list)


class PrepsubbandResult(BaseModel):
    dm_low: float
    dm_step: float
    num_dms: int
    num_subbands: int
    output_prefix: str
    dat_files: list[str] = Field(default_factory=list)
    inf_files: list[str] = Field(default_factory=list)


class RealfftResult(BaseModel):
    input_dat: str
    fft_file: str | None = None
    inf_file: str | None = None


class AccelCandidate(BaseModel):
    cand_num: int | None = None
    sigma: float | None = None
    frequency_hz: float | None = None
    period_ms: float | None = None
    z: float | None = None
    num_harmonics: int | None = None
    dm: float | None = None


class AccelsearchResult(BaseModel):
    zmax: int
    numharm: int
    input_fft: str
    wmax: int | None = None  # jerk-search w, when supported by the image
    sigma: float | None = None
    ncpus: int | None = None
    accel_cand_file: str | None = None
    accel_txtcand_file: str | None = None
    cand_count: int | None = None
    top_candidates: list[AccelCandidate] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class SinglePulseSearchResult(BaseModel):
    threshold: float
    max_width_s: float
    input_dat_files: list[str] = Field(default_factory=list)
    singlepulse_files: list[str] = Field(default_factory=list)
    ps_file: str | None = None
    pulse_count: int | None = None
    max_snr: float | None = None


class SiftCandidate(BaseModel):
    cand_id: str | None = None
    dm: float | None = None
    sigma: float | None = None
    period_ms: float | None = None
    frequency_hz: float | None = None
    num_hits: int | None = None
    note: str | None = None


class SiftingResult(BaseModel):
    input_accel_files: list[str] = Field(default_factory=list)
    min_num_dms: int
    low_dm_cutoff: float
    sigma_threshold: float
    surviving_candidates: list[SiftCandidate] = Field(default_factory=list)
    total_input_cands: int | None = None
    total_surviving: int | None = None
    summary_file: str | None = None


class ZapbirdsResult(BaseModel):
    input_fft: str
    zaplist_file: str
    zapped_fft: str | None = None
    inf_file: str | None = None
    num_zaps: int | None = None


class RrattrapResult(BaseModel):
    input_singlepulse_files: list[str] = Field(default_factory=list)
    inf_file: str | None = None
    groups_file: str | None = None
    num_groups: int | None = None
    output_files: list[str] = Field(default_factory=list)


class MakeSpdResult(BaseModel):
    raw_file: str
    groups_file: str
    input_singlepulse_files: list[str] = Field(default_factory=list)
    mask_file: str | None = None
    spd_files: list[str] = Field(default_factory=list)


class PlotSpdResult(BaseModel):
    input_spd: str
    png_file: str | None = None


class SinglePulseDiagnosticStage(BaseModel):
    """One stage of the composite single-pulse diagnostic workflow."""

    stage: Literal["single_pulse_search", "rrattrap", "make_spd", "plot_spd"]
    run_id: str
    status: RunStatus
    error: str | None = None


class SinglePulseDiagnosticResult(BaseModel):
    """Composite result of the canonical PRESTO single-pulse diagnostic chain.

    Stages run in order: ``single_pulse_search → rrattrap → make_spd → plot_spd``.
    Each stage's run_id is preserved so the caller can inspect intermediates.
    ``spd_files`` enumerates the canonical PRESTO single-pulse artifacts produced
    by ``make_spd``; ``plot_pngs`` are the diagnostic plots rendered by
    ``plot_spd`` for each ``.spd`` file.
    """

    stages: list[SinglePulseDiagnosticStage] = Field(default_factory=list)
    singlepulse_files: list[str] = Field(default_factory=list)
    groups_file: str | None = None
    spd_files: list[str] = Field(default_factory=list)
    plot_pngs: list[str] = Field(default_factory=list)


class WaterfallerCompatNotes(BaseModel):
    """Audit trail for non-default behavior applied by waterfaller_headless.

    All flags default to ``False`` / ``None`` so a manifest with no compat
    fallbacks records the same value as a missing sidecar file.
    """

    compat_mode: bool = False
    psrfits_hotfix_applied: bool = False
    psrfits2fil_converted: bool = False
    converted_input_path: str | None = None


class WaterfallerResult(BaseModel):
    input_raw: str
    start_s: float
    duration_s: float
    dm: float
    mask_file: str | None = None
    output_file: str | None = None
    compat_notes: WaterfallerCompatNotes | None = None


class GetTOAsResult(BaseModel):
    pfd_file: str
    template_file: str
    num_subints: int
    num_subbands: int
    num_toas: int
    toa_lines: list[str] = Field(default_factory=list)


class RunSummary(BaseModel):
    """One row of ``list_runs`` output (a thin slice of RunManifest)."""

    run_id: str
    tool: str
    status: RunStatus
    started_at: datetime
    duration_s: float | None = None
    exit_code: int | None = None
    manifest_uri: str


# -- The wire envelope ----------------------------------------------------------

T = TypeVar("T", bound=BaseModel)


class ToolRunResult(BaseModel, Generic[T]):
    """What every tool returns. ``result`` is None when ``status != SUCCESS``."""

    run_id: str
    status: RunStatus
    result: T | None = None
    manifest_uri: str
    stdout_uri: str
    stderr_uri: str
    artifact_uris: list[str] = Field(default_factory=list)
    error: str | None = None


# -- Backend layer (in/out of docker_backend.run) -------------------------------


class BackendResult(BaseModel):
    """What :func:`docker_backend.run` returns to the executor."""

    model_config = ConfigDict(frozen=True)

    status: RunStatus
    exit_code: int | None
    stdout: str
    stderr: str
    duration_s: float
    error: str | None = None


# -- Utility / navigation models (capabilities layer) ---------------------------

DataFileLikelyType = Literal["filterbank", "fits", "psrfits", "text", "unknown"]


class DataFileSummary(BaseModel):
    relative_path: str
    size_bytes: int
    modified_at: datetime
    extension: str | None = None
    likely_type: DataFileLikelyType = "unknown"


class ListDataFilesResult(BaseModel):
    data_dir_label: str
    count: int
    files: list[DataFileSummary] = Field(default_factory=list)


EnvironmentCheckStatus = Literal["OK", "WARN", "ERROR"]


class EnvironmentCheck(BaseModel):
    name: str
    status: EnvironmentCheckStatus
    message: str
    remediation: str | None = None


# -- Runtime capability / readiness layer ---------------------------------------

RuntimeCheckStatus = Literal["OK", "WARN", "ERROR", "UNKNOWN"]


class RuntimeCheck(BaseModel):
    """One capability probe against the configured PRESTO Docker image."""

    name: str
    kind: Literal["binary", "python_module", "help", "flag"]
    status: RuntimeCheckStatus
    message: str
    remediation: str | None = None
    raw_output: str | None = None  # clipped probe stdout/stderr excerpt


class PrestoRuntimeCapabilities(BaseModel):
    """Snapshot of what the PRESTO image provides (binaries + python modules)."""

    image: str
    checked_at: datetime
    from_cache: bool = False
    binaries: list[RuntimeCheck] = Field(default_factory=list)
    python_modules: list[RuntimeCheck] = Field(default_factory=list)


class ToolReadiness(BaseModel):
    """Whether one MCP tool's runtime dependencies are satisfied by the image."""

    tool_name: str
    status: RuntimeCheckStatus
    checks: list[RuntimeCheck] = Field(default_factory=list)
    blocking: bool = False  # True when status == ERROR (tool will fail if invoked)


class RuntimeCompatibilityResult(BaseModel):
    """Full image-vs-tools compatibility report."""

    image: str
    status: RuntimeCheckStatus
    capabilities: PrestoRuntimeCapabilities
    tool_readiness: list[ToolReadiness] = Field(default_factory=list)


class ValidateEnvironmentResult(BaseModel):
    status: EnvironmentCheckStatus
    checks: list[EnvironmentCheck] = Field(default_factory=list)
    runtime_compatibility: RuntimeCompatibilityResult | None = None


class ArtifactType(StrEnum):
    RFI = "rfi"
    TIME_SERIES = "time_series"
    FFT = "fft"
    ACCEL_CANDIDATES = "accel_candidates"
    SINGLE_PULSE = "single_pulse"
    SPD = "spd"
    PLOTS = "plots"
    FOLD = "fold"
    TIMING = "timing"
    OTHER = "other"


class ArtifactSummary(BaseModel):
    name: str
    size_bytes: int
    modified_at: datetime
    likely_type: ArtifactType = ArtifactType.OTHER
    resource_uri: str
    is_inline_readable: bool = False


class InspectArtifactsResult(BaseModel):
    run_id: str
    artifacts: list[ArtifactSummary] = Field(default_factory=list)


class RunStructuredSummary(BaseModel):
    run_id: str
    tool: str
    status: RunStatus
    started_at: datetime
    duration_s: float | None = None
    exit_code: int | None = None
    error: str | None = None
    inputs: dict[str, str] = Field(default_factory=dict)
    artifact_counts: dict[ArtifactType, int] = Field(default_factory=dict)
    artifacts_by_type: dict[ArtifactType, list[str]] = Field(default_factory=dict)
    next_suggested_tools: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


# -- Additional PRESTO tool result schemas (data prep / RFI / fold QC / advanced)


class Psrfits2FilResult(BaseModel):
    input_file: str
    output_prefix: str
    fil_files: list[str] = Field(default_factory=list)
    inf_files: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class DownsampleFilterbankResult(BaseModel):
    input_file: str
    factor: int
    output_file: str | None = None
    notes: list[str] = Field(default_factory=list)


class FbTruncateResult(BaseModel):
    input_file: str
    output_file: str | None = None
    output_prefix: str
    start_sample: int | None = None
    num_samples: int | None = None
    notes: list[str] = Field(default_factory=list)


class RfifindStatsResult(BaseModel):
    stats_file: str
    mask_file: str | None = None
    summary_file: str | None = None
    bad_channels: list[int] = Field(default_factory=list)
    bad_intervals: list[int] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class Pfd2PngResult(BaseModel):
    pfd_file: str
    png_file: str | None = None
    ps_file: str | None = None
    notes: list[str] = Field(default_factory=list)


class PfdZapResult(BaseModel):
    pfd_file: str
    output_pfd_file: str | None = None
    zap_commands_file: str | None = None
    notes: list[str] = Field(default_factory=list)


class MakeZaplistResult(BaseModel):
    input_file: str
    zaplist_file: str | None = None
    notes: list[str] = Field(default_factory=list)


class WeightsToIgnorechanResult(BaseModel):
    weights_file: str
    ignorechan_file: str | None = None
    ignore_channels: list[int] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class FourierFoldProfileSummary(BaseModel):
    period_s: float | None = None
    frequency_hz: float | None = None
    dm: float | None = None
    num_bins: int | None = None


class FourierFoldResult(BaseModel):
    fft_file: str
    profile_file: str | None = None
    plot_file: str | None = None
    summary: FourierFoldProfileSummary | None = None
    notes: list[str] = Field(default_factory=list)


class SumProfilesResult(BaseModel):
    input_profile_files: list[str] = Field(default_factory=list)
    output_profile_file: str | None = None
    plot_file: str | None = None
    notes: list[str] = Field(default_factory=list)


class SearchBinCandidate(BaseModel):
    cand_num: int | None = None
    frequency_hz: float | None = None
    period_ms: float | None = None
    sigma: float | None = None
    orb_p_s: float | None = None
    note: str | None = None


class SearchBinResult(BaseModel):
    fft_file: str
    candidate_files: list[str] = Field(default_factory=list)
    top_candidates: list[SearchBinCandidate] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


# -- New tools: stacksearch / simple_zapbirds / compare_periods / binary_info ----


class StackSearchCandidate(BaseModel):
    cand_num: int | None = None
    sigma: float | None = None
    frequency_hz: float | None = None
    period_ms: float | None = None
    dm: float | None = None
    note: str | None = None


class StackSearchResult(BaseModel):
    fft_files: list[str] = Field(default_factory=list)
    candidate_files: list[str] = Field(default_factory=list)
    summary_file: str | None = None
    top_candidates: list[StackSearchCandidate] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class SimpleZapbirdsResult(BaseModel):
    input_fft_files: list[str] = Field(default_factory=list)
    staged_fft_files: list[str] = Field(default_factory=list)
    birds_file: str
    zapped_fft_files: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class PeriodMatch(BaseModel):
    par_file: str
    pulsar_name: str | None = None
    candidate_period_ms: float
    matched_period_ms: float
    # n > 0: candidate ≈ pulsar_period / n (n-th harmonic; n=1 fundamental).
    # n < 0: candidate ≈ pulsar_period * |n| (|n|-th subharmonic).
    harmonic: int
    delta: float  # relative difference at the matched harmonic
    confidence_label: Literal["exact", "near", "weak", "unknown"]


class ComparePeriodsResult(BaseModel):
    period_ms: float
    par_files: list[str] = Field(default_factory=list)
    tolerance: float
    max_harmonic: int
    matches: list[PeriodMatch] = Field(default_factory=list)
    summary: str = ""
    notes: list[str] = Field(default_factory=list)


class BinaryInfoResult(BaseModel):
    par_file: str
    inf_file: str | None = None
    is_binary: bool = False
    pulsar_name: str | None = None
    binary_summary: dict[str, float | str | None] = Field(default_factory=dict)
    plot_files: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class CandidateReportPdfResult(BaseModel):
    pdf_file: str
    page_count: int
    title: str | None = None
    included_artifacts: list[str] = Field(default_factory=list)
    skipped_artifacts: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    resource_uri: str
