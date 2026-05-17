"""FastMCP STDIO server. The only module that imports FastMCP.

Tools registered:

  * ``presto.readfile``        — wraps ``readfile``
  * ``presto.rfifind``         — wraps ``rfifind -time <t> -o <prefix>``
  * ``presto.prepfold``        — wraps ``prepfold -noxwin -p <p> -dm <dm> ...``
  * ``presto.list_runs``       — reflection
  * ``presto.get_run_manifest``— reflection

Resources registered (URI templates):

  * ``presto://runs/{run_id}/manifest``
  * ``presto://runs/{run_id}/stdout``
  * ``presto://runs/{run_id}/stderr``
  * ``presto://runs/{run_id}/artifacts/{filename}``

This file translates between the MCP edge and the typed core. Validation,
sandboxing, and orchestration live in the modules under ``presto_mcp/``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from . import resources as resource_handlers
from . import tools as _tools_pkg  # noqa: F401 — keep the package side-effect free
from .config import Settings, ensure_runtime_dirs, get_settings, run_health_check
from .docker_backend import BackendProtocol, DockerBackend
from .errors import (
    DockerInvocationError,
    ManifestError,
    ParserError,
    PathSecurityError,
    PolicyViolationError,
)
from .models import (
    AccelsearchResult,
    DDplanResult,
    DownsampleFilterbankResult,
    FbTruncateResult,
    FourierFoldResult,
    GetTOAsResult,
    InspectArtifactsResult,
    ListDataFilesResult,
    MakeSpdResult,
    MakeZaplistResult,
    Pfd2PngResult,
    PfdZapResult,
    PlotSpdResult,
    PrepdataResult,
    PrepfoldResult,
    PrepsubbandResult,
    Psrfits2FilResult,
    ReadfileMetadata,
    RealfftResult,
    RfifindStatsResult,
    RfifindSummary,
    RrattrapResult,
    RunManifest,
    RunStructuredSummary,
    RunSummary,
    SearchBinResult,
    SiftingResult,
    SinglePulseSearchResult,
    SumProfilesResult,
    ToolRunResult,
    ValidateEnvironmentResult,
    WaterfallerResult,
    WeightsToIgnorechanResult,
    ZapbirdsResult,
)
from .prompts import (
    build_explain_failed_run,
    build_fold_known_candidate_plan,
    build_fold_qc_plan,
    build_generate_candidate_report_plan,
    build_inspect_observation_plan,
    build_periodic_advanced_search_plan,
    build_periodic_search_plan,
    build_prepare_filterbank_plan,
    build_rfi_mitigation_plan,
    build_single_pulse_full_plan,
    build_single_pulse_search_plan,
    build_tool_selection_guide,
)
from .tools import list_runs as list_runs_tool
from .tools.accelsearch import run_accelsearch
from .tools.ddplan import run_ddplan
from .tools.downsample_filterbank import run_downsample_filterbank
from .tools.fb_truncate import run_fb_truncate
from .tools.fourier_fold import run_fourier_fold
from .tools.get_toas import run_get_toas
from .tools.list_data_files import run_list_data_files
from .tools.make_spd import run_make_spd
from .tools.makezaplist import run_makezaplist
from .tools.pfd2png import run_pfd2png
from .tools.pfdzap import run_pfdzap
from .tools.plot_spd import run_plot_spd
from .tools.prepdata import run_prepdata
from .tools.prepfold import run_prepfold
from .tools.prepsubband import run_prepsubband
from .tools.psrfits2fil import run_psrfits2fil
from .tools.readfile import run_readfile
from .tools.realfft import run_realfft
from .tools.rfifind import run_rfifind
from .tools.rfifind_stats import run_rfifind_stats
from .tools.rrattrap import run_rrattrap
from .tools.search_bin import run_search_bin
from .tools.sifting import run_sifting
from .tools.single_pulse_search import run_single_pulse_search
from .tools.sum_profiles import run_sum_profiles
from .tools.summarize_run import inspect_artifacts as _inspect_artifacts
from .tools.summarize_run import summarize_run as _summarize_run
from .tools.validate_environment import run_validate_environment
from .tools.waterfaller import run_waterfaller
from .tools.weights_to_ignorechan import run_weights_to_ignorechan
from .tools.zapbirds import run_zapbirds

log = logging.getLogger("presto_mcp.server")

# --- App + backend (singletons) ------------------------------------------------

mcp = FastMCP("presto-mcp")


def _build_backend() -> BackendProtocol:
    return DockerBackend()


# Allow tests to install a fake backend before the server boots.
_backend: BackendProtocol | None = None
_settings: Settings | None = None


def _backend_for_tools() -> BackendProtocol:
    global _backend
    if _backend is None:
        _backend = _build_backend()
    return _backend


def _settings_for_tools() -> Settings:
    global _settings
    if _settings is None:
        _settings = get_settings()
    return _settings


def set_backend(b: BackendProtocol) -> None:
    """Tests use this to inject a FakeDockerBackend before the server runs."""
    global _backend
    _backend = b


def set_settings(s: Settings) -> None:
    """Tests use this to inject a Settings before the server runs."""
    global _settings
    _settings = s


# --- Tools ---------------------------------------------------------------------


@mcp.tool(
    name="presto.readfile",
    description=(
        "Run PRESTO 'readfile' inside Docker on a file under data/. Returns "
        "structured metadata (telescope, source name, central freq, channels, "
        "sample time, etc.) plus URIs for manifest/stdout/stderr/artifacts. "
        "Path must be relative to the configured DATA_DIR; absolute paths and "
        "'..' segments are rejected. "
        "Set background=true when the MCP client times out before Docker finishes "
        "(~60s for 150MB filterbank files); poll presto.get_run_manifest with run_id."
    ),
)
async def presto_readfile(
    input_file: Annotated[
        str,
        Field(description="Path to a PRESTO-readable file relative to DATA_DIR."),
    ],
    background: Annotated[
        bool,
        Field(
            default=False,
            description=(
                "If true, return immediately with status RUNNING and poll "
                "presto.get_run_manifest until SUCCESS/FAILED/TIMEOUT."
            ),
        ),
    ] = False,
) -> ToolRunResult[ReadfileMetadata]:
    return await asyncio.to_thread(
        run_readfile,
        input_file,
        backend=_backend_for_tools(),
        settings=_settings_for_tools(),
        background=background,
    )


@mcp.tool(
    name="presto.rfifind",
    description=(
        "Run PRESTO 'rfifind' inside Docker. Generates .mask/.rfi/.stats "
        "artifacts and a summary (intervals, RFI instances, % masked). "
        "Time is the integration length in seconds (0.1–3600)."
    ),
)
async def presto_rfifind(
    input_file: Annotated[
        str,
        Field(description="Path to a PRESTO-readable file relative to DATA_DIR."),
    ],
    time: Annotated[
        float,
        Field(default=2.0, ge=0.1, le=3600.0, description="Integration length, seconds."),
    ] = 2.0,
    output_prefix: Annotated[
        str | None,
        Field(
            default=None,
            description=(
                "Filename prefix for outputs (alnum, '_', '-', '+', '.'; max 128). "
                "Defaults to 'rfi'."
            ),
        ),
    ] = None,
    background: Annotated[
        bool,
        Field(
            default=False,
            description="Return immediately with RUNNING; poll get_run_manifest.",
        ),
    ] = False,
) -> ToolRunResult[RfifindSummary]:
    return await asyncio.to_thread(
        run_rfifind,
        input_file,
        backend=_backend_for_tools(),
        time=time,
        output_prefix=output_prefix,
        settings=_settings_for_tools(),
        background=background,
    )


@mcp.tool(
    name="presto.prepfold",
    description=(
        "Run PRESTO 'prepfold' inside Docker in Mode A (period + DM). Generates "
        "a .pfd plus .pfd.ps/.pfd.bestprof artifacts. Use this only when you "
        "already have a candidate period and DM; broader 'fold by accel cand' "
        "is a future tool."
    ),
)
async def presto_prepfold(
    input_file: Annotated[
        str,
        Field(description="Path to a PRESTO-readable file relative to DATA_DIR."),
    ],
    period_seconds: Annotated[
        float,
        Field(gt=0.0, le=60.0, description="Candidate spin period in seconds."),
    ],
    dm: Annotated[
        float,
        Field(ge=0.0, le=10_000.0, description="Dispersion measure (pc cm^-3)."),
    ],
    output_prefix: Annotated[
        str | None,
        Field(
            default=None,
            description="Filename prefix for outputs. Defaults to 'fold'.",
        ),
    ] = None,
    background: Annotated[
        bool,
        Field(
            default=False,
            description="Return immediately with RUNNING; poll get_run_manifest.",
        ),
    ] = False,
) -> ToolRunResult[PrepfoldResult]:
    return await asyncio.to_thread(
        run_prepfold,
        input_file,
        period_seconds,
        dm,
        backend=_backend_for_tools(),
        output_prefix=output_prefix,
        settings=_settings_for_tools(),
        background=background,
    )


@mcp.tool(
    name="presto.prepdata",
    description=(
        "Run PRESTO 'prepdata' inside Docker to dedisperse one DM trial into a "
        "single-precision .dat time series (+ .inf header). Optionally accepts "
        "a mask_file (relative to DATA_DIR). Input path is relative to DATA_DIR."
    ),
)
async def presto_prepdata(
    input_file: Annotated[
        str,
        Field(description="Path to a PRESTO-readable file relative to DATA_DIR."),
    ],
    dm: Annotated[
        float,
        Field(ge=0.0, le=10_000.0, description="Dispersion measure (pc cm^-3)."),
    ],
    output_prefix: Annotated[
        str | None,
        Field(default=None, description="Output filename prefix. Defaults to 'prep'."),
    ] = None,
    mask_file: Annotated[
        str | None,
        Field(
            default=None,
            description="Optional rfifind .mask file relative to DATA_DIR.",
        ),
    ] = None,
    background: Annotated[
        bool,
        Field(default=False, description="Return RUNNING; poll get_run_manifest."),
    ] = False,
) -> ToolRunResult[PrepdataResult]:
    return await asyncio.to_thread(
        run_prepdata,
        input_file,
        dm,
        backend=_backend_for_tools(),
        output_prefix=output_prefix,
        mask_file=mask_file,
        settings=_settings_for_tools(),
        background=background,
    )


@mcp.tool(
    name="presto.ddplan",
    description=(
        "Run PRESTO 'DDplan.py' inside Docker to compute an optimal DM-trial "
        "plan. Pure compute (no data input). Returns a list of passes "
        "(low_dm, dm_step, num_dms, downsamp) for use with presto.prepsubband."
    ),
)
async def presto_ddplan(
    dm_low: Annotated[float, Field(ge=0.0, le=10_000.0, description="Lowest DM to plan.")],
    dm_high: Annotated[float, Field(ge=0.0, le=10_000.0, description="Highest DM to plan.")],
    freq_mhz: Annotated[float, Field(gt=0.0, description="Center frequency (MHz).")],
    bw_mhz: Annotated[float, Field(gt=0.0, description="Total bandwidth (MHz).")],
    num_channels: Annotated[int, Field(ge=1, le=4096, description="Number of frequency channels.")],
    sample_time_us: Annotated[
        float,
        Field(gt=0.0, description="Native sample time in microseconds."),
    ],
    num_subbands: Annotated[
        int | None,
        Field(default=None, ge=1, le=4096, description="Optional number of subbands."),
    ] = None,
    background: Annotated[
        bool,
        Field(default=False, description="Return RUNNING; poll get_run_manifest."),
    ] = False,
) -> ToolRunResult[DDplanResult]:
    return await asyncio.to_thread(
        run_ddplan,
        backend=_backend_for_tools(),
        dm_low=dm_low,
        dm_high=dm_high,
        freq_mhz=freq_mhz,
        bw_mhz=bw_mhz,
        num_channels=num_channels,
        sample_time_us=sample_time_us,
        num_subbands=num_subbands,
        settings=_settings_for_tools(),
        background=background,
    )


@mcp.tool(
    name="presto.prepsubband",
    description=(
        "Run PRESTO 'prepsubband' inside Docker to dedisperse a range of DM "
        "trials in a single pass. Produces one <prefix>_DM<dm>.dat per trial. "
        "Use presto.ddplan first to choose dm_low/dm_step/num_dms/num_subbands."
    ),
)
async def presto_prepsubband(
    input_file: Annotated[
        str,
        Field(description="Path to a PRESTO-readable file relative to DATA_DIR."),
    ],
    dm_low: Annotated[float, Field(ge=0.0, le=10_000.0, description="Lowest DM.")],
    dm_step: Annotated[float, Field(gt=0.0, description="DM step.")],
    num_dms: Annotated[int, Field(ge=1, le=100_000, description="Number of DM trials.")],
    num_subbands: Annotated[int, Field(ge=1, le=4096, description="Number of subbands.")],
    output_prefix: Annotated[
        str | None,
        Field(default=None, description="Output filename prefix. Defaults to 'sub'."),
    ] = None,
    mask_file: Annotated[
        str | None,
        Field(default=None, description="Optional rfifind .mask file relative to DATA_DIR."),
    ] = None,
    background: Annotated[
        bool,
        Field(default=False, description="Return RUNNING; poll get_run_manifest."),
    ] = False,
) -> ToolRunResult[PrepsubbandResult]:
    return await asyncio.to_thread(
        run_prepsubband,
        input_file,
        backend=_backend_for_tools(),
        dm_low=dm_low,
        dm_step=dm_step,
        num_dms=num_dms,
        num_subbands=num_subbands,
        output_prefix=output_prefix,
        mask_file=mask_file,
        settings=_settings_for_tools(),
        background=background,
    )


@mcp.tool(
    name="presto.realfft",
    description=(
        "Run PRESTO 'realfft' inside Docker to FFT a dedispersed .dat into a "
        ".fft. input_file is interpreted as '<run_id>/artifacts/<file>.dat' "
        "relative to RUNS_DIR (typically from a prior prepdata/prepsubband run). "
        "The .dat (+ sibling .inf) is copied into the current run's artifacts/."
    ),
)
async def presto_realfft(
    input_file: Annotated[
        str,
        Field(description="<run_id>/artifacts/<file>.dat relative to RUNS_DIR."),
    ],
    background: Annotated[
        bool,
        Field(default=False, description="Return RUNNING; poll get_run_manifest."),
    ] = False,
) -> ToolRunResult[RealfftResult]:
    return await asyncio.to_thread(
        run_realfft,
        input_file,
        backend=_backend_for_tools(),
        settings=_settings_for_tools(),
        background=background,
    )


@mcp.tool(
    name="presto.accelsearch",
    description=(
        "Run PRESTO 'accelsearch' inside Docker for Fourier / acceleration "
        "candidate search on a .fft (from a prior realfft run). Produces "
        "ACCEL_<zmax> + .txtcand artifacts and a typed top-N candidate list. "
        "input_file is interpreted relative to RUNS_DIR."
    ),
)
async def presto_accelsearch(
    input_file: Annotated[
        str,
        Field(description="<run_id>/artifacts/<file>.fft relative to RUNS_DIR."),
    ],
    zmax: Annotated[
        int,
        Field(default=200, ge=0, le=1200, description="Max Fourier z to search."),
    ] = 200,
    numharm: Annotated[
        int,
        Field(default=8, description="Number of harmonics to sum (1,2,4,8,16,32)."),
    ] = 8,
    background: Annotated[
        bool,
        Field(default=False, description="Return RUNNING; poll get_run_manifest."),
    ] = False,
) -> ToolRunResult[AccelsearchResult]:
    return await asyncio.to_thread(
        run_accelsearch,
        input_file,
        backend=_backend_for_tools(),
        zmax=zmax,
        numharm=numharm,
        settings=_settings_for_tools(),
        background=background,
    )


@mcp.tool(
    name="presto.single_pulse_search",
    description=(
        "Run PRESTO 'single_pulse_search.py' inside Docker over one or more "
        ".dat files (from prior prepdata/prepsubband runs) to detect bright "
        "single pulses (FRBs, giant pulses). Each input gets a .singlepulse; "
        "a summary .ps plot is written when multiple inputs are provided."
    ),
)
async def presto_single_pulse_search(
    input_files: Annotated[
        list[str],
        Field(description="List of <run_id>/artifacts/<file>.dat paths relative to RUNS_DIR."),
    ],
    threshold: Annotated[
        float,
        Field(default=5.0, ge=1.0, le=50.0, description="Sigma threshold for detection."),
    ] = 5.0,
    max_width_s: Annotated[
        float,
        Field(default=0.1, gt=0.0, le=10.0, description="Max boxcar width in seconds."),
    ] = 0.1,
    background: Annotated[
        bool,
        Field(default=False, description="Return RUNNING; poll get_run_manifest."),
    ] = False,
) -> ToolRunResult[SinglePulseSearchResult]:
    return await asyncio.to_thread(
        run_single_pulse_search,
        input_files,
        backend=_backend_for_tools(),
        threshold=threshold,
        max_width_s=max_width_s,
        settings=_settings_for_tools(),
        background=background,
    )


@mcp.tool(
    name="presto.sifting",
    description=(
        "Run PRESTO 'ACCEL_sift.py' inside Docker over many ACCEL_* candidate "
        "files (from prior accelsearch runs) to dedupe and rank survivors. "
        "Inputs are interpreted relative to RUNS_DIR and staged into the new "
        "run's staging/ directory."
    ),
)
async def presto_sifting(
    accel_files: Annotated[
        list[str],
        Field(description="List of <run_id>/artifacts/<file>_ACCEL_<zmax> paths relative to RUNS_DIR."),
    ],
    min_num_dms: Annotated[
        int,
        Field(default=2, ge=1, le=1000, description="Min DM trials a candidate must appear in."),
    ] = 2,
    low_dm_cutoff: Annotated[
        float,
        Field(default=2.0, ge=0.0, le=10_000.0, description="Discard candidates below this DM."),
    ] = 2.0,
    sigma_threshold: Annotated[
        float,
        Field(default=4.0, ge=1.0, le=50.0, description="Min sigma for survivors."),
    ] = 4.0,
    background: Annotated[
        bool,
        Field(default=False, description="Return RUNNING; poll get_run_manifest."),
    ] = False,
) -> ToolRunResult[SiftingResult]:
    return await asyncio.to_thread(
        run_sifting,
        accel_files,
        backend=_backend_for_tools(),
        min_num_dms=min_num_dms,
        low_dm_cutoff=low_dm_cutoff,
        sigma_threshold=sigma_threshold,
        settings=_settings_for_tools(),
        background=background,
    )


@mcp.tool(
    name="presto.get_toas",
    description=(
        "Run PRESTO 'get_TOAs.py' inside Docker to compute Times of Arrival "
        "from a folded .pfd plus a Gaussian template. pfd_file is "
        "'<run_id>/artifacts/<file>.pfd' relative to RUNS_DIR; template_file "
        "is relative to DATA_DIR. Returns TEMPO/TEMPO2 TOA lines."
    ),
)
async def presto_get_toas(
    pfd_file: Annotated[
        str,
        Field(description="<run_id>/artifacts/<file>.pfd relative to RUNS_DIR."),
    ],
    template_file: Annotated[
        str,
        Field(description="Gaussian template (.gaussians/.template) relative to DATA_DIR."),
    ],
    num_subints: Annotated[
        int,
        Field(default=1, ge=1, le=4096, description="Number of sub-integrations."),
    ] = 1,
    num_subbands: Annotated[
        int,
        Field(default=1, ge=1, le=4096, description="Number of frequency subbands."),
    ] = 1,
    background: Annotated[
        bool,
        Field(default=False, description="Return RUNNING; poll get_run_manifest."),
    ] = False,
) -> ToolRunResult[GetTOAsResult]:
    return await asyncio.to_thread(
        run_get_toas,
        pfd_file,
        template_file,
        backend=_backend_for_tools(),
        num_subints=num_subints,
        num_subbands=num_subbands,
        settings=_settings_for_tools(),
        background=background,
    )


@mcp.tool(
    name="presto.zapbirds",
    description=(
        "Run PRESTO 'zapbirds' inside Docker to apply a zaplist to a .fft "
        "(modifies the .fft in place). input_fft is "
        "'<run_id>/artifacts/<file>.fft' relative to RUNS_DIR (from a prior "
        "realfft run); zaplist_file is a text birds/zap file relative to "
        "DATA_DIR. The .fft (+ sibling .inf) is staged into the current run's "
        "artifacts/ and zapped there."
    ),
)
async def presto_zapbirds(
    input_fft: Annotated[
        str,
        Field(description="<run_id>/artifacts/<file>.fft relative to RUNS_DIR."),
    ],
    zaplist_file: Annotated[
        str,
        Field(description="Zaplist / birds file relative to DATA_DIR."),
    ],
    baryv: Annotated[
        float | None,
        Field(default=None, description="Average barycentric velocity (-baryv)."),
    ] = None,
    nfft: Annotated[
        int | None,
        Field(default=None, ge=0, description="Override -N nfft."),
    ] = None,
    background: Annotated[
        bool,
        Field(default=False, description="Return RUNNING; poll get_run_manifest."),
    ] = False,
) -> ToolRunResult[ZapbirdsResult]:
    return await asyncio.to_thread(
        run_zapbirds,
        input_fft,
        zaplist_file,
        backend=_backend_for_tools(),
        baryv=baryv,
        nfft=nfft,
        settings=_settings_for_tools(),
        background=background,
    )


@mcp.tool(
    name="presto.rrattrap",
    description=(
        "Run PRESTO 'rrattrap.py' inside Docker to group single-pulse events "
        "from one or more .singlepulse files (from prior single_pulse_search "
        "runs) plus the .inf header. Writes groups.txt into the run's "
        "artifacts/. All inputs are '<run_id>/artifacts/...' relative to RUNS_DIR."
    ),
)
async def presto_rrattrap(
    singlepulse_files: Annotated[
        list[str],
        Field(description="List of <run_id>/artifacts/<file>.singlepulse paths."),
    ],
    inf_file: Annotated[
        str,
        Field(description="<run_id>/artifacts/<file>.inf relative to RUNS_DIR."),
    ],
    min_group: Annotated[
        int | None,
        Field(default=None, ge=1, description="Minimum events per group (--min-group)."),
    ] = None,
    use_dm_plan: Annotated[
        bool,
        Field(default=False, description="Pass --use-DMplan."),
    ] = False,
    background: Annotated[
        bool,
        Field(default=False, description="Return RUNNING; poll get_run_manifest."),
    ] = False,
) -> ToolRunResult[RrattrapResult]:
    return await asyncio.to_thread(
        run_rrattrap,
        singlepulse_files,
        inf_file,
        backend=_backend_for_tools(),
        min_group=min_group,
        use_dm_plan=use_dm_plan,
        settings=_settings_for_tools(),
        background=background,
    )


@mcp.tool(
    name="presto.make_spd",
    description=(
        "Run PRESTO 'make_spd.py' inside Docker to produce single-pulse "
        "diagnostic .spd files. Reads a rrattrap groups.txt + raw "
        "filterbank/PSRFITS + .singlepulse files (and optional rfifind .mask). "
        "raw_file and mask_file are relative to DATA_DIR; groups_file and "
        "singlepulse_files are '<run_id>/artifacts/...' relative to RUNS_DIR."
    ),
)
async def presto_make_spd(
    raw_file: Annotated[
        str,
        Field(description="Raw filterbank/PSRFITS file relative to DATA_DIR."),
    ],
    groups_file: Annotated[
        str,
        Field(description="<run_id>/artifacts/<groups>.txt relative to RUNS_DIR."),
    ],
    singlepulse_files: Annotated[
        list[str],
        Field(description="List of <run_id>/artifacts/<file>.singlepulse paths."),
    ],
    mask_file: Annotated[
        str | None,
        Field(default=None, description="Optional rfifind .mask file relative to DATA_DIR."),
    ] = None,
    output_prefix: Annotated[
        str | None,
        Field(default=None, description="Output basename for .spd files. Defaults to 'spd'."),
    ] = None,
    apply_mask: Annotated[
        bool,
        Field(default=False, description="Pass --mask to enable masking (requires mask_file)."),
    ] = False,
    background: Annotated[
        bool,
        Field(default=False, description="Return RUNNING; poll get_run_manifest."),
    ] = False,
) -> ToolRunResult[MakeSpdResult]:
    return await asyncio.to_thread(
        run_make_spd,
        raw_file,
        groups_file,
        singlepulse_files,
        backend=_backend_for_tools(),
        mask_file=mask_file,
        output_prefix=output_prefix,
        apply_mask=apply_mask,
        settings=_settings_for_tools(),
        background=background,
    )


@mcp.tool(
    name="presto.plot_spd",
    description=(
        "Run PRESTO 'plot_spd.py' inside Docker to render a PNG/PS diagnostic "
        "plot from a .spd (and optional .singlepulse files). All inputs are "
        "'<run_id>/artifacts/...' relative to RUNS_DIR."
    ),
)
async def presto_plot_spd(
    input_spd: Annotated[
        str,
        Field(description="<run_id>/artifacts/<file>.spd relative to RUNS_DIR."),
    ],
    singlepulse_files: Annotated[
        list[str] | None,
        Field(default=None, description="Optional list of <run_id>/artifacts/<file>.singlepulse."),
    ] = None,
    output_prefix: Annotated[
        str | None,
        Field(default=None, description="Output filename basename. Defaults to 'spdplot'."),
    ] = None,
    just_waterfall: Annotated[
        bool,
        Field(default=False, description="Pass --just-waterfall."),
    ] = False,
    background: Annotated[
        bool,
        Field(default=False, description="Return RUNNING; poll get_run_manifest."),
    ] = False,
) -> ToolRunResult[PlotSpdResult]:
    return await asyncio.to_thread(
        run_plot_spd,
        input_spd,
        backend=_backend_for_tools(),
        singlepulse_files=singlepulse_files,
        output_prefix=output_prefix,
        just_waterfall=just_waterfall,
        settings=_settings_for_tools(),
        background=background,
    )


@mcp.tool(
    name="presto.waterfaller",
    description=(
        "Run PRESTO 'waterfaller.py' inside Docker to render a dynamic-spectrum "
        "(waterfall) image around a candidate (start_s, duration_s, dm) for a "
        "raw filterbank/PSRFITS file under DATA_DIR. Optional mask_file is "
        "also relative to DATA_DIR. Requires the PRESTO image's PNG-tagged "
        "variant to write the figure into the working directory."
    ),
)
async def presto_waterfaller(
    input_file: Annotated[
        str,
        Field(description="Raw filterbank/PSRFITS file relative to DATA_DIR."),
    ],
    start_s: Annotated[
        float,
        Field(ge=0.0, description="Start time of the waterfall, seconds."),
    ],
    duration_s: Annotated[
        float,
        Field(gt=0.0, le=600.0, description="Duration of the waterfall, seconds."),
    ],
    dm: Annotated[
        float,
        Field(ge=0.0, le=10_000.0, description="DM to use when dedispersing for plot."),
    ],
    mask_file: Annotated[
        str | None,
        Field(default=None, description="Optional rfifind .mask file relative to DATA_DIR."),
    ] = None,
    nsub: Annotated[
        int | None,
        Field(default=None, ge=1, le=4096, description="Number of subbands (-s)."),
    ] = None,
    nbins: Annotated[
        int | None,
        Field(default=None, ge=1, description="Number of time bins (-n)."),
    ] = None,
    downsamp: Annotated[
        int | None,
        Field(default=None, ge=1, description="Downsample factor (--downsamp)."),
    ] = None,
    background: Annotated[
        bool,
        Field(default=False, description="Return RUNNING; poll get_run_manifest."),
    ] = False,
) -> ToolRunResult[WaterfallerResult]:
    return await asyncio.to_thread(
        run_waterfaller,
        input_file,
        backend=_backend_for_tools(),
        start_s=start_s,
        duration_s=duration_s,
        dm=dm,
        mask_file=mask_file,
        nsub=nsub,
        nbins=nbins,
        downsamp=downsamp,
        settings=_settings_for_tools(),
        background=background,
    )


@mcp.tool(
    name="presto.list_runs",
    description=(
        "List recent PRESTO runs from this server's runs/ directory (newest first). "
        "Returns one row per run with run_id, tool, status, started_at, duration, "
        "exit code and a manifest URI."
    ),
)
async def presto_list_runs(
    limit: Annotated[
        int,
        Field(default=50, ge=1, le=1000, description="Max rows to return."),
    ] = 50,
) -> list[RunSummary]:
    return await asyncio.to_thread(
        list_runs_tool.list_runs, limit=limit, settings=_settings_for_tools()
    )


@mcp.tool(
    name="presto.get_run_manifest",
    description="Return the full manifest JSON for a given run_id.",
)
async def presto_get_run_manifest(
    run_id: Annotated[str, Field(description="A run_id from presto.list_runs.")],
) -> RunManifest:
    return await asyncio.to_thread(
        list_runs_tool.get_run_manifest, run_id, settings=_settings_for_tools()
    )


# --- Resources -----------------------------------------------------------------


@mcp.resource(
    "presto://runs/{run_id}/manifest",
    description="JSON manifest for one PRESTO run.",
    mime_type="application/json",
)
def _resource_manifest(run_id: str) -> str:
    return resource_handlers.read_manifest_resource(_settings_for_tools(), run_id)


@mcp.resource(
    "presto://runs/{run_id}/stdout",
    description="stdout captured for one PRESTO run.",
    mime_type="text/plain",
)
def _resource_stdout(run_id: str) -> str:
    return resource_handlers.read_log_resource(_settings_for_tools(), run_id, "stdout")


@mcp.resource(
    "presto://runs/{run_id}/stderr",
    description="stderr captured for one PRESTO run.",
    mime_type="text/plain",
)
def _resource_stderr(run_id: str) -> str:
    return resource_handlers.read_log_resource(_settings_for_tools(), run_id, "stderr")


@mcp.resource(
    "presto://runs/{run_id}/artifacts/{filename}",
    description=(
        "An artifact produced by a PRESTO run. Small text files are returned "
        "inline; large or binary files return a JSON descriptor pointing at the "
        "host-side path."
    ),
)
def _resource_artifact(run_id: str, filename: str) -> str:
    content, _mime = resource_handlers.read_artifact_resource(
        _settings_for_tools(), run_id, filename
    )
    return content


# --- Additional PRESTO tools (data prep / RFI / fold QC / advanced) -----------


@mcp.tool(
    name="presto.psrfits2fil",
    description=(
        "Run PRESTO 'psrfits2fil.py' inside Docker to convert PSRFITS search-"
        "format to a SIGPROC .fil (+ optional .inf). Input is relative to "
        "DATA_DIR; outputs land in runs/<run_id>/artifacts/."
    ),
)
async def presto_psrfits2fil(
    input_file: Annotated[
        str,
        Field(description="PSRFITS file relative to DATA_DIR."),
    ],
    output_prefix: Annotated[
        str | None,
        Field(default=None, description="Output filename prefix. Defaults to 'fil'."),
    ] = None,
    background: Annotated[
        bool,
        Field(default=False, description="Return RUNNING; poll get_run_manifest."),
    ] = False,
) -> ToolRunResult[Psrfits2FilResult]:
    return await asyncio.to_thread(
        run_psrfits2fil,
        input_file,
        backend=_backend_for_tools(),
        output_prefix=output_prefix,
        settings=_settings_for_tools(),
        background=background,
    )


@mcp.tool(
    name="presto.downsample_filterbank",
    description=(
        "Run PRESTO 'downsample_filterbank.py' inside Docker to produce a "
        "factor-downsampled .fil for faster debugging / lighter analysis. "
        "factor ∈ [2, 1024]. Input is relative to DATA_DIR."
    ),
)
async def presto_downsample_filterbank(
    input_file: Annotated[
        str,
        Field(description="Filterbank file relative to DATA_DIR."),
    ],
    factor: Annotated[
        int,
        Field(ge=2, le=1024, description="Downsample factor (2..1024)."),
    ],
    background: Annotated[
        bool,
        Field(default=False, description="Return RUNNING; poll get_run_manifest."),
    ] = False,
) -> ToolRunResult[DownsampleFilterbankResult]:
    return await asyncio.to_thread(
        run_downsample_filterbank,
        input_file,
        backend=_backend_for_tools(),
        factor=factor,
        settings=_settings_for_tools(),
        background=background,
    )


@mcp.tool(
    name="presto.fb_truncate",
    description=(
        "Run PRESTO 'fb_truncate.py' inside Docker to cut a sample window from "
        "a filterbank. Samples-mode only: provide start_sample (default 0) and "
        "num_samples. Use presto.readfile first to convert seconds → samples."
    ),
)
async def presto_fb_truncate(
    input_file: Annotated[
        str,
        Field(description="Filterbank file relative to DATA_DIR."),
    ],
    num_samples: Annotated[
        int,
        Field(ge=1, le=10**10, description="Number of samples to keep."),
    ],
    start_sample: Annotated[
        int,
        Field(default=0, ge=0, le=10**12, description="Starting sample index."),
    ] = 0,
    output_prefix: Annotated[
        str | None,
        Field(default=None, description="Output filename prefix. Defaults to 'trunc'."),
    ] = None,
    background: Annotated[
        bool,
        Field(default=False, description="Return RUNNING; poll get_run_manifest."),
    ] = False,
) -> ToolRunResult[FbTruncateResult]:
    return await asyncio.to_thread(
        run_fb_truncate,
        input_file,
        backend=_backend_for_tools(),
        start_sample=start_sample,
        num_samples=num_samples,
        output_prefix=output_prefix,
        settings=_settings_for_tools(),
        background=background,
    )


@mcp.tool(
    name="presto.rfifind_stats",
    description=(
        "Run PRESTO 'rfifind_stats.py' inside Docker to summarize a prior "
        "rfifind run's .stats (+ optional .mask) into structured "
        "bad_channels / bad_intervals. Inputs are '<run_id>/artifacts/...' "
        "relative to RUNS_DIR."
    ),
)
async def presto_rfifind_stats(
    stats_file: Annotated[
        str,
        Field(description="<run_id>/artifacts/<file>.stats relative to RUNS_DIR."),
    ],
    mask_file: Annotated[
        str | None,
        Field(
            default=None,
            description="Optional <run_id>/artifacts/<file>.mask relative to RUNS_DIR.",
        ),
    ] = None,
    background: Annotated[
        bool,
        Field(default=False, description="Return RUNNING; poll get_run_manifest."),
    ] = False,
) -> ToolRunResult[RfifindStatsResult]:
    return await asyncio.to_thread(
        run_rfifind_stats,
        stats_file,
        backend=_backend_for_tools(),
        mask_file=mask_file,
        settings=_settings_for_tools(),
        background=background,
    )


@mcp.tool(
    name="presto.pfd2png",
    description=(
        "[experimental] Run PRESTO 'pfd2png.sh' inside Docker to render a "
        ".pfd to .png/.ps. Availability depends on the configured PRESTO "
        "image — verify with presto.validate_environment first. Input is "
        "'<run_id>/artifacts/<file>.pfd' relative to RUNS_DIR."
    ),
)
async def presto_pfd2png(
    pfd_file: Annotated[
        str,
        Field(description="<run_id>/artifacts/<file>.pfd relative to RUNS_DIR."),
    ],
    background: Annotated[
        bool,
        Field(default=False, description="Return RUNNING; poll get_run_manifest."),
    ] = False,
) -> ToolRunResult[Pfd2PngResult]:
    return await asyncio.to_thread(
        run_pfd2png,
        pfd_file,
        backend=_backend_for_tools(),
        settings=_settings_for_tools(),
        background=background,
    )


@mcp.tool(
    name="presto.pfdzap",
    description=(
        "[experimental] Run PRESTO 'pfdzap.py' inside Docker to apply simple "
        "interval/channel zapping to a .pfd. zap_commands is a list of strict "
        "'<low>:<high>' tokens (max 512); arbitrary shell input is rejected. "
        "pfd_file is '<run_id>/artifacts/<file>.pfd' relative to RUNS_DIR."
    ),
)
async def presto_pfdzap(
    pfd_file: Annotated[
        str,
        Field(description="<run_id>/artifacts/<file>.pfd relative to RUNS_DIR."),
    ],
    zap_commands: Annotated[
        list[str],
        Field(
            description="List of '<low>:<high>' tokens (e.g. ['10:20','60:70']).",
            min_length=1,
            max_length=512,
        ),
    ],
    output_prefix: Annotated[
        str | None,
        Field(default=None, description="Output filename prefix. Defaults to 'pfdzap'."),
    ] = None,
    background: Annotated[
        bool,
        Field(default=False, description="Return RUNNING; poll get_run_manifest."),
    ] = False,
) -> ToolRunResult[PfdZapResult]:
    return await asyncio.to_thread(
        run_pfdzap,
        pfd_file,
        backend=_backend_for_tools(),
        zap_commands=zap_commands,
        output_prefix=output_prefix,
        settings=_settings_for_tools(),
        background=background,
    )


@mcp.tool(
    name="presto.makezaplist",
    description=(
        "[experimental] Run PRESTO 'makezaplist.py' inside Docker to build a "
        ".zaplist from a .birds (or similar) file under DATA_DIR. Verify the "
        "script is available in the configured image with "
        "presto.validate_environment first."
    ),
)
async def presto_makezaplist(
    input_file: Annotated[
        str,
        Field(description="Input file (typically .birds) relative to DATA_DIR."),
    ],
    background: Annotated[
        bool,
        Field(default=False, description="Return RUNNING; poll get_run_manifest."),
    ] = False,
) -> ToolRunResult[MakeZaplistResult]:
    return await asyncio.to_thread(
        run_makezaplist,
        input_file,
        backend=_backend_for_tools(),
        settings=_settings_for_tools(),
        background=background,
    )


@mcp.tool(
    name="presto.weights_to_ignorechan",
    description=(
        "[experimental] Run PRESTO 'weights_to_ignorechan.py' inside Docker "
        "to convert a .weights or .mask artifact from a prior run into a "
        "channel-skip list. weights_file is '<run_id>/artifacts/<file>' "
        "relative to RUNS_DIR. Optional threshold ∈ [0, 1]."
    ),
)
async def presto_weights_to_ignorechan(
    weights_file: Annotated[
        str,
        Field(description="<run_id>/artifacts/<file>.weights (or .mask) relative to RUNS_DIR."),
    ],
    threshold: Annotated[
        float | None,
        Field(default=None, ge=0.0, le=1.0, description="Optional weight threshold."),
    ] = None,
    background: Annotated[
        bool,
        Field(default=False, description="Return RUNNING; poll get_run_manifest."),
    ] = False,
) -> ToolRunResult[WeightsToIgnorechanResult]:
    return await asyncio.to_thread(
        run_weights_to_ignorechan,
        weights_file,
        backend=_backend_for_tools(),
        threshold=threshold,
        settings=_settings_for_tools(),
        background=background,
    )


@mcp.tool(
    name="presto.fourier_fold",
    description=(
        "[experimental] Run PRESTO 'fourier_fold.py' inside Docker to fold a "
        ".fft at a known (period_seconds OR frequency_hz, optional dm). "
        "Exactly one of period_seconds / frequency_hz must be supplied. "
        "fft_file is '<run_id>/artifacts/<file>.fft' relative to RUNS_DIR."
    ),
)
async def presto_fourier_fold(
    fft_file: Annotated[
        str,
        Field(description="<run_id>/artifacts/<file>.fft relative to RUNS_DIR."),
    ],
    period_seconds: Annotated[
        float | None,
        Field(default=None, gt=0.0, le=60.0, description="Candidate spin period (s)."),
    ] = None,
    frequency_hz: Annotated[
        float | None,
        Field(default=None, gt=0.0, description="Candidate spin frequency (Hz)."),
    ] = None,
    dm: Annotated[
        float | None,
        Field(default=None, ge=0.0, le=10_000.0, description="Dispersion measure (pc cm^-3)."),
    ] = None,
    background: Annotated[
        bool,
        Field(default=False, description="Return RUNNING; poll get_run_manifest."),
    ] = False,
) -> ToolRunResult[FourierFoldResult]:
    return await asyncio.to_thread(
        run_fourier_fold,
        fft_file,
        backend=_backend_for_tools(),
        period_seconds=period_seconds,
        frequency_hz=frequency_hz,
        dm=dm,
        settings=_settings_for_tools(),
        background=background,
    )


@mcp.tool(
    name="presto.sum_profiles",
    description=(
        "[experimental] Run PRESTO 'sum_profiles.py' inside Docker to combine "
        "many profile files (.bestprof / .prof) from prior runs. Each entry "
        "of profile_files is '<run_id>/artifacts/<file>' relative to RUNS_DIR."
    ),
)
async def presto_sum_profiles(
    profile_files: Annotated[
        list[str],
        Field(
            description="List of '<run_id>/artifacts/<file>' relative to RUNS_DIR.",
            min_length=1,
            max_length=4096,
        ),
    ],
    background: Annotated[
        bool,
        Field(default=False, description="Return RUNNING; poll get_run_manifest."),
    ] = False,
) -> ToolRunResult[SumProfilesResult]:
    return await asyncio.to_thread(
        run_sum_profiles,
        profile_files,
        backend=_backend_for_tools(),
        settings=_settings_for_tools(),
        background=background,
    )


@mcp.tool(
    name="presto.search_bin",
    description=(
        "[advanced] Run PRESTO 'search_bin' inside Docker for phase-modulation "
        "/ sideband search on a .fft (binary-pulsar candidates). Optional "
        "[low_hz, high_hz] band ∈ [0, 5e5] Hz with low < high. fft_file is "
        "'<run_id>/artifacts/<file>.fft' relative to RUNS_DIR."
    ),
)
async def presto_search_bin(
    fft_file: Annotated[
        str,
        Field(description="<run_id>/artifacts/<file>.fft relative to RUNS_DIR."),
    ],
    low_hz: Annotated[
        float | None,
        Field(default=None, ge=0.0, description="Optional lower frequency bound (Hz)."),
    ] = None,
    high_hz: Annotated[
        float | None,
        Field(default=None, gt=0.0, description="Optional upper frequency bound (Hz)."),
    ] = None,
    background: Annotated[
        bool,
        Field(default=False, description="Return RUNNING; poll get_run_manifest."),
    ] = False,
) -> ToolRunResult[SearchBinResult]:
    return await asyncio.to_thread(
        run_search_bin,
        fft_file,
        backend=_backend_for_tools(),
        low_hz=low_hz,
        high_hz=high_hz,
        settings=_settings_for_tools(),
        background=background,
    )


# --- Utility tools (no PRESTO execution) --------------------------------------


@mcp.tool(
    name="presto.list_data_files",
    description=(
        "List files available under PRESTO_DATA_DIR (no Docker, no PRESTO). "
        "Returns relative paths, size, mtime, extension and a coarse "
        "likely_type ({filterbank, fits, psrfits, text, unknown}). Optional "
        "extension filter (e.g. ['.fil', '.fits']). Hidden files are excluded "
        "unless include_hidden=true."
    ),
)
async def presto_list_data_files(
    limit: Annotated[
        int,
        Field(default=100, ge=1, le=10_000, description="Max rows to return."),
    ] = 100,
    extensions: Annotated[
        list[str] | None,
        Field(default=None, description="Optional extension allowlist, e.g. ['.fil','.fits']."),
    ] = None,
    include_hidden: Annotated[
        bool,
        Field(default=False, description="Include dot-prefixed entries."),
    ] = False,
) -> ListDataFilesResult:
    return await asyncio.to_thread(
        run_list_data_files,
        limit=limit,
        extensions=extensions,
        include_hidden=include_hidden,
        settings=_settings_for_tools(),
    )


@mcp.tool(
    name="presto.validate_environment",
    description=(
        "Structured local-environment diagnostic. Checks settings, data/runs/"
        "outputs/logs directories, docker CLI presence and (optionally) the "
        "PRESTO image, plus policy sanity (cpus, memory_mb, timeout_s). Never "
        "executes PRESTO. Each check returns OK/WARN/ERROR with remediation."
    ),
)
async def presto_validate_environment(
    check_image: Annotated[
        bool,
        Field(
            default=True,
            description="If true, also run 'docker image inspect <PRESTO_IMAGE>'.",
        ),
    ] = True,
) -> ValidateEnvironmentResult:
    return await asyncio.to_thread(
        run_validate_environment,
        check_image=check_image,
        settings=_settings_for_tools(),
    )


@mcp.tool(
    name="presto.summarize_run",
    description=(
        "Structured summary of one existing run: status, duration, exit_code, "
        "inputs, artifact counts grouped by type (rfi / time_series / fft / "
        "accel_candidates / single_pulse / spd / plots / fold / timing / other) "
        "and suggested next PRESTO tools to call. Reads the manifest + walks "
        "artifacts/; never reads artifact contents."
    ),
)
async def presto_summarize_run(
    run_id: Annotated[str, Field(description="A run_id from presto.list_runs.")],
) -> RunStructuredSummary:
    return await asyncio.to_thread(
        _summarize_run, run_id, settings=_settings_for_tools()
    )


@mcp.tool(
    name="presto.inspect_artifacts",
    description=(
        "Per-artifact index for one run: name, size, mtime, classified type, "
        "resource URI and an is_inline_readable hint (small text artifacts). "
        "Does not read artifact contents."
    ),
)
async def presto_inspect_artifacts(
    run_id: Annotated[str, Field(description="A run_id from presto.list_runs.")],
) -> InspectArtifactsResult:
    return await asyncio.to_thread(
        _inspect_artifacts, run_id, settings=_settings_for_tools()
    )


# --- Navigation resources ------------------------------------------------------


@mcp.resource(
    "presto://data",
    description="JSON index of files under PRESTO_DATA_DIR (relative paths only).",
    mime_type="application/json",
)
def _resource_data_index() -> str:
    result = run_list_data_files(settings=_settings_for_tools())
    return result.model_dump_json(indent=2)


@mcp.resource(
    "presto://runs",
    description="JSON index of recent runs (newest first).",
    mime_type="application/json",
)
def _resource_runs_index() -> str:
    summaries = list_runs_tool.list_runs(settings=_settings_for_tools())
    payload = [s.model_dump(mode="json") for s in summaries]
    return json.dumps({"count": len(payload), "runs": payload}, indent=2)


@mcp.resource(
    "presto://runs/{run_id}/summary",
    description="Structured RunStructuredSummary JSON for one run.",
    mime_type="application/json",
)
def _resource_run_summary(run_id: str) -> str:
    return _summarize_run(run_id, settings=_settings_for_tools()).model_dump_json(indent=2)


@mcp.resource(
    "presto://runs/{run_id}/artifacts",
    description="JSON index of artifacts for one run (no inlined contents).",
    mime_type="application/json",
)
def _resource_run_artifacts(run_id: str) -> str:
    return _inspect_artifacts(run_id, settings=_settings_for_tools()).model_dump_json(indent=2)


# --- Prompts (guidance, not execution) -----------------------------------------


@mcp.prompt(
    name="presto.inspect_observation_plan",
    description=(
        "Guide the model through inspecting one observation file with "
        "presto.readfile and reporting key metadata. No heavy search is run."
    ),
)
def _prompt_inspect_observation_plan(input_file: str, goal: str | None = None) -> str:
    return build_inspect_observation_plan(input_file, goal=goal)


@mcp.prompt(
    name="presto.single_pulse_search_plan",
    description=(
        "Conceptual single-pulse search pipeline (readfile → rfifind → ddplan "
        "→ prepsubband/prepdata → single_pulse_search → rrattrap → make_spd → "
        "plot_spd → waterfaller). Guidance only; tools must be called by client."
    ),
)
def _prompt_single_pulse_search_plan(
    input_file: str,
    dm_low: float | None = None,
    dm_high: float | None = None,
    threshold: float | None = None,
) -> str:
    return build_single_pulse_search_plan(
        input_file, dm_low=dm_low, dm_high=dm_high, threshold=threshold
    )


@mcp.prompt(
    name="presto.periodic_search_plan",
    description=(
        "Conceptual periodic / acceleration search pipeline (readfile → rfifind "
        "→ ddplan → prepdata/prepsubband → realfft → zapbirds → accelsearch → "
        "sifting → prepfold → get_toas). Guidance only."
    ),
)
def _prompt_periodic_search_plan(
    input_file: str,
    dm_low: float | None = None,
    dm_high: float | None = None,
    zmax: int | None = None,
) -> str:
    return build_periodic_search_plan(
        input_file, dm_low=dm_low, dm_high=dm_high, zmax=zmax
    )


@mcp.prompt(
    name="presto.fold_known_candidate_plan",
    description=(
        "Guide the model through folding a known (period, DM) candidate with "
        "presto.prepfold and optionally computing TOAs."
    ),
)
def _prompt_fold_known_candidate_plan(
    input_file: str, period_seconds: float, dm: float
) -> str:
    return build_fold_known_candidate_plan(input_file, period_seconds, dm)


@mcp.prompt(
    name="presto.explain_failed_run",
    description=(
        "Guide the model through diagnosing a failed run via manifest + stdout "
        "+ stderr, classifying the failure mode and suggesting one next action."
    ),
)
def _prompt_explain_failed_run(run_id: str) -> str:
    return build_explain_failed_run(run_id)


@mcp.prompt(
    name="presto.generate_candidate_report_plan",
    description=(
        "Guide the model through summarising candidate evidence across one or "
        "more runs. Strictly distinguishes artifact / noise / candidate / "
        "detection; does not assert scientific confirmations."
    ),
)
def _prompt_generate_candidate_report_plan(run_id: str | None = None) -> str:
    return build_generate_candidate_report_plan(run_id)


@mcp.prompt(
    name="presto.prepare_filterbank_plan",
    description=(
        "Guide the model through data preparation (readfile → psrfits2fil / "
        "fb_truncate / downsample_filterbank as needed). No search is launched."
    ),
)
def _prompt_prepare_filterbank_plan(input_file: str, goal: str | None = None) -> str:
    return build_prepare_filterbank_plan(input_file, goal=goal)


@mcp.prompt(
    name="presto.rfi_mitigation_plan",
    description=(
        "Guide the model through RFI mitigation: rfifind → rfifind_stats → "
        "weights_to_ignorechan / makezaplist → zapbirds, and how to use mask "
        "vs zaplist vs ignorechan."
    ),
)
def _prompt_rfi_mitigation_plan(
    input_file: str, existing_rfifind_run_id: str | None = None
) -> str:
    return build_rfi_mitigation_plan(
        input_file, existing_rfifind_run_id=existing_rfifind_run_id
    )


@mcp.prompt(
    name="presto.fold_qc_plan",
    description=(
        "Guide the model through quality-checking a folded .pfd: inspect "
        ".bestprof/.ps/.png, optionally pfd2png / pfdzap / get_toas / "
        "sum_profiles. Refuses scientific claims without artifact evidence."
    ),
)
def _prompt_fold_qc_plan(pfd_file: str, goal: str | None = None) -> str:
    return build_fold_qc_plan(pfd_file, goal=goal)


@mcp.prompt(
    name="presto.periodic_advanced_search_plan",
    description=(
        "Guide the model through the periodic-search pipeline plus advanced "
        "add-ons (fourier_fold for known candidates; search_bin for binary "
        "orbital sidebands when binary_search=true)."
    ),
)
def _prompt_periodic_advanced_search_plan(
    input_file: str, binary_search: bool = False
) -> str:
    return build_periodic_advanced_search_plan(input_file, binary_search=binary_search)


@mcp.prompt(
    name="presto.single_pulse_full_plan",
    description=(
        "Guide the model through the full single-pulse pipeline (readfile → "
        "rfifind → rfifind_stats → ddplan → prepsubband → single_pulse_search "
        "→ rrattrap → make_spd → plot_spd → waterfaller). Suggests fb_truncate "
        "for debugging large inputs."
    ),
)
def _prompt_single_pulse_full_plan(
    input_file: str,
    dm_low: float | None = None,
    dm_high: float | None = None,
) -> str:
    return build_single_pulse_full_plan(
        input_file, dm_low=dm_low, dm_high=dm_high
    )


@mcp.prompt(
    name="presto.tool_selection_guide",
    description=(
        "Categorized index mapping a free-form task description to the right "
        "typed tool(s): data prep / RFI / dedispersion / periodic search / "
        "single-pulse / folding / timing / visualization / debugging / "
        "advanced. Flags experimental tools explicitly."
    ),
)
def _prompt_tool_selection_guide(task: str) -> str:
    return build_tool_selection_guide(task)


# --- Entrypoint ----------------------------------------------------------------


def _configure_logging() -> None:
    level = os.environ.get("PRESTO_LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def main() -> None:
    _configure_logging()
    s = get_settings()
    ensure_runtime_dirs(s)
    try:
        run_health_check(s)
    except Exception as e:  # noqa: BLE001
        log.error("startup health check failed: %s", e)
        raise SystemExit(2) from e

    set_settings(s)
    log.info("presto-mcp starting (image=%s, data=%s)", s.image, s.data_dir)
    mcp.run()


# Errors we expect FastMCP to surface as ordinary tool errors. Keeping them
# here as a manifest for readers — FastMCP serializes exception types via repr.
_EXPORTED_ERRORS = (
    PathSecurityError,
    PolicyViolationError,
    DockerInvocationError,
    ParserError,
    ManifestError,
)


if __name__ == "__main__":
    main()
