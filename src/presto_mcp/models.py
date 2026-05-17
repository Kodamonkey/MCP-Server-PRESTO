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
    freq_mhz: float
    bw_mhz: float
    num_channels: int
    sample_time_us: float
    passes: list[DDplanPass] = Field(default_factory=list)


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
    accel_cand_file: str | None = None
    accel_txtcand_file: str | None = None
    cand_count: int | None = None
    top_candidates: list[AccelCandidate] = Field(default_factory=list)


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


class WaterfallerResult(BaseModel):
    input_raw: str
    start_s: float
    duration_s: float
    dm: float
    mask_file: str | None = None
    output_file: str | None = None


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
