"""Pydantic v2 schemas for the modern reporting layer.

Three groups:

  * **Candidate model** — one normalized detection (``Candidate``).
  * **Artifact model** — one published file (``Artifact``).
  * **Run-level models** — ``ArtifactPolicy``, ``ReportOptions``,
    ``RunReportSummary`` (``summary.json``), ``ReportManifest`` (``manifest.json``).

Scientific parameters are always ``None`` when unknown — never invented.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# --- Candidates ---------------------------------------------------------------


class CandidateType(StrEnum):
    SINGLE_PULSE = "single_pulse"
    PERIODIC = "periodic"
    ACCELERATION = "acceleration"
    FOLDED = "folded"
    RRAT_GROUP = "rrat_group"
    UNKNOWN = "unknown"


class CandidatePaths(BaseModel):
    """Relative paths (under ``outputs/<run_id>/``) of per-candidate artifacts."""

    visual_artifact_path: str | None = None
    waterfall_png_path: str | None = None
    waterfall_pdf_path: str | None = None
    diagnostic_png_path: str | None = None
    candidate_json_path: str | None = None


class Candidate(BaseModel):
    """One normalized candidate / event from any PRESTO source stage."""

    candidate_id: str
    candidate_type: CandidateType = CandidateType.UNKNOWN
    source_stage: str | None = None
    source_file: str | None = None

    dm: float | None = None
    snr_or_sigma: float | None = None
    time_sec: float | None = None
    sample: int | None = None
    period_sec: float | None = None
    frequency_hz: float | None = None
    acceleration_or_z: float | None = None
    width_bins: int | None = None
    downfact: int | None = None
    rank: int | None = None
    folded: bool = False

    classification_hint: str | None = None
    is_known_pulsar_candidate: bool = False
    is_frb_like: bool = False
    is_rfi_like: bool = False

    paths: CandidatePaths = Field(default_factory=CandidatePaths)
    raw_metadata: dict[str, str] = Field(default_factory=dict)
    notes: str | None = None


# --- Artifacts ----------------------------------------------------------------


class ReportArtifactKind(StrEnum):
    SUMMARY_JSON = "summary_json"
    CANDIDATES_CSV = "candidates_csv"
    VISUAL_PNG = "visual_png"
    THUMBNAIL = "thumbnail"
    WATERFALL_PNG = "waterfall_png"
    WATERFALL_PDF = "waterfall_pdf"
    REPORT_HTML = "report_html"
    REPORT_MD = "report_md"
    CANDIDATE_JSON = "candidate_json"
    DIAGNOSTIC_PNG = "diagnostic_png"
    RAW_EXPORT = "raw_export"
    ASSET = "asset"
    MANIFEST = "manifest"


class Artifact(BaseModel):
    """One file published under ``outputs/<run_id>/``."""

    artifact_id: str
    artifact_kind: ReportArtifactKind
    path: str  # relative to outputs/<run_id>/
    source_file: str | None = None
    created_by_tool: str | None = None
    candidate_id: str | None = None
    mime_type: str | None = None
    description: str | None = None
    size_bytes: int | None = None


# --- Policy / options ---------------------------------------------------------


class ArtifactPolicy(BaseModel):
    """Which modern artifacts to publish for one report bundle."""

    export_summary_json: bool = True
    export_candidates_csv: bool = True
    export_visual_png: bool = False
    export_thumbnails: bool = False
    export_waterfall_png: bool = False
    export_waterfall_pdf: bool = False
    export_report_html: bool = False
    export_report_markdown: bool = False
    export_original_presto_outputs: bool = False
    cleanup_intermediate_files: bool = True
    max_candidates_for_waterfalls: int = 100
    max_candidates_in_html: int = 500
    default_waterfall_cmap: str = "inferno"


class IntentionFlags(BaseModel):
    """Explicit, prompt-derived intent flags used to route an artifact policy.

    The LLM sets these from the user request; no NLP happens server-side.
    """

    wants_metadata_only: bool = False
    wants_candidates: bool = False
    wants_visuals: bool = False
    wants_waterfalls: bool = False
    wants_waterfall_pdf: bool = False
    wants_report: bool = False
    wants_no_extra_files: bool = False
    wants_original_presto_outputs: bool = False


class ReportOptions(BaseModel):
    """Cosmetic / rendering knobs for one report bundle."""

    self_contained_html: bool = False
    waterfall_cmap: str = "inferno"
    waterfall_window_sec: float = 1.0
    title: str | None = None
    include_observability_links: bool = True


# --- Summary (summary.json) ---------------------------------------------------


class ObservationMetadata(BaseModel):
    """Observational metadata extracted from headers / readfile / .inf."""

    file_type: str | None = None
    telescope: str | None = None
    instrument: str | None = None
    source_name: str | None = None
    mjd_start: float | None = None
    start_time: str | None = None
    duration_sec: float | None = None
    nchans: int | None = None
    tsamp_us: float | None = None
    fch1_mhz: float | None = None
    central_freq_mhz: float | None = None
    bandwidth_mhz: float | None = None
    bits_per_sample: int | None = None


class CandidateCounts(BaseModel):
    total: int = 0
    single_pulse: int = 0
    periodic: int = 0
    acceleration: int = 0
    folded: int = 0
    rrat_group: int = 0
    unknown: int = 0


class RfiSummary(BaseModel):
    available: bool = False
    mask_files: list[str] = Field(default_factory=list)
    bad_channels: list[int] = Field(default_factory=list)
    bad_intervals: list[int] = Field(default_factory=list)
    pct_masked: float | None = None
    notes: list[str] = Field(default_factory=list)


class RunReportSummary(BaseModel):
    """``summary.json`` — scientific + operational summary of a report run."""

    schema_version: Literal[1] = 1
    run_id: str
    input_file: str | None = None
    generated_at: datetime
    status: Literal["success", "partial", "failed"] = "success"

    observation: ObservationMetadata = Field(default_factory=ObservationMetadata)
    dm_trials: int | None = None

    candidate_counts: CandidateCounts = Field(default_factory=CandidateCounts)
    top_candidates: list[Candidate] = Field(default_factory=list)
    rfi_summary: RfiSummary = Field(default_factory=RfiSummary)

    tools_executed: list[str] = Field(default_factory=list)
    failed_tools: list[str] = Field(default_factory=list)
    artifact_policy: ArtifactPolicy

    total_runtime_sec: float | None = None
    warning_count: int = 0
    error_count: int = 0
    logs_available: bool = False
    status_file: str | None = None

    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


# --- Manifest (manifest.json) -------------------------------------------------


class ReportManifest(BaseModel):
    """``manifest.json`` — inventory of one report bundle."""

    model_config = ConfigDict(validate_assignment=True)

    schema_version: Literal[1] = 1
    run_id: str
    input_file: str | None = None
    created_at: datetime
    status: Literal["success", "partial", "failed"] = "success"

    tools_executed: list[str] = Field(default_factory=list)
    artifact_policy: ArtifactPolicy

    summary_json: str | None = None
    candidates_csv: str | None = None
    report_html: str | None = None
    report_md: str | None = None

    visuals: list[Artifact] = Field(default_factory=list)
    thumbnails: list[Artifact] = Field(default_factory=list)
    waterfall_png: list[Artifact] = Field(default_factory=list)
    waterfall_pdf: list[Artifact] = Field(default_factory=list)
    candidate_artifacts: list[Artifact] = Field(default_factory=list)
    raw_presto_exports: list[Artifact] = Field(default_factory=list)

    log_paths: dict[str, str] = Field(default_factory=dict)
    status_md: str | None = None
    timeline_json: str | None = None

    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class ReportToolResult(BaseModel):
    """What every reporting MCP tool returns to the client."""

    run_id: str
    tool: str
    status: Literal["success", "partial", "failed"] = "success"
    output_dir: str
    manifest_path: str | None = None
    summary_json: str | None = None
    candidates_csv: str | None = None
    report_html: str | None = None
    report_md: str | None = None
    candidate_count: int = 0
    artifact_count: int = 0
    artifacts: list[Artifact] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


__all__ = [
    "Artifact",
    "ArtifactPolicy",
    "Candidate",
    "CandidateCounts",
    "CandidatePaths",
    "CandidateType",
    "IntentionFlags",
    "ObservationMetadata",
    "ReportArtifactKind",
    "ReportManifest",
    "ReportOptions",
    "ReportToolResult",
    "RfiSummary",
    "RunReportSummary",
]
