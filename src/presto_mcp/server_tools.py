"""MCP tool registration for presto_mcp.server.

This module intentionally does not import FastMCP. The entrypoint owns the
FastMCP instance and passes it in so server.py remains the only FastMCP import.
"""

from __future__ import annotations

import asyncio
import functools
import inspect
from collections.abc import Callable
from typing import Annotated, Any, Literal

from pydantic import Field

from .config import Settings
from .docker_backend import BackendProtocol
from .models import (
    AccelsearchResult,
    BinaryInfoResult,
    CandidateReportPdfResult,
    ComparePeriodsResult,
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
    SimpleZapbirdsResult,
    SinglePulseDiagnosticResult,
    SinglePulseSearchResult,
    StackSearchResult,
    SumProfilesResult,
    ToolRunResult,
    ValidateEnvironmentResult,
    WaterfallerResult,
    WeightsToIgnorechanResult,
    ZapbirdsResult,
)
from .observability.redaction import summarize_args
from .observability.tool_logging import ToolCallContext
from .reporting.schemas import ReportToolResult
from .tool_metadata import PROFILE_NAMES, resolve_profile
from .tools import list_runs as list_runs_tool
from .tools.accelsearch import run_accelsearch
from .tools.binary_info import run_binary_info
from .tools.compare_periods import run_compare_periods
from .tools.compile_candidate_report_pdf import run_compile_candidate_report_pdf
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
from .tools.reporting import (
    run_export_candidates_csv,
    run_generate_candidate_waterfalls,
    run_generate_modern_report_bundle,
    run_generate_report_html,
    run_generate_report_markdown,
    run_generate_summary_json,
    run_generate_visual_artifacts,
)
from .tools.rfifind import run_rfifind
from .tools.rfifind_stats import run_rfifind_stats
from .tools.rrattrap import run_rrattrap
from .tools.search_bin import run_search_bin
from .tools.sifting import run_sifting
from .tools.simple_zapbirds import run_simple_zapbirds
from .tools.single_pulse_diagnostic import run_single_pulse_diagnostic
from .tools.single_pulse_search import run_single_pulse_search
from .tools.stacksearch import run_stacksearch
from .tools.sum_profiles import run_sum_profiles
from .tools.summarize_run import inspect_artifacts as _inspect_artifacts
from .tools.summarize_run import summarize_run as _summarize_run
from .tools.validate_environment import run_validate_environment
from .tools.waterfaller import run_waterfaller
from .tools.weights_to_ignorechan import run_weights_to_ignorechan
from .tools.zapbirds import run_zapbirds

# Shared annotation for the repeated `background` flag (previously duplicated
# inline in ~34 tool signatures).
_BackgroundParam = Annotated[
    bool,
    Field(
        default=False,
        description=(
            "If true, return immediately with status RUNNING; poll "
            "presto.get_run_manifest until SUCCESS/FAILED/TIMEOUT."
        ),
    ),
]

# Injected into every tool by the `tool` decorator (no per-tool edits): an
# optional client-supplied workflow id that groups a pipeline's tool calls into
# one observability run (logs/runs/<id>/ with a live status.md).
_WORKFLOW_RUN_ID_PARAM = inspect.Parameter(
    "workflow_run_id",
    inspect.Parameter.KEYWORD_ONLY,
    default=None,
    annotation=Annotated[
        str | None,
        Field(
            default=None,
            description=(
                "Optional workflow run id (YYYYMMDDTHHMMSSZ-XXXXXX) grouping this "
                "call's structured logs under logs/runs/<id>/ with a live "
                "status.md. Omit for standalone calls; reuse the same id across a "
                "pipeline to get one grouped timeline."
            ),
        ),
    ],
)


def register_tools(
    mcp: Any,
    _backend_for_tools: Callable[[], BackendProtocol],
    _settings_for_tools: Callable[[], Settings],
) -> None:
    # --- Profile-aware registration ------------------------------------------------
    # PRESTO_TOOL_PROFILE selects which tools are exposed. The `tool` wrapper
    # registers a tool with FastMCP only when the active profile includes it;
    # otherwise the decorated function is left defined-but-unregistered.
    try:
        _profile = _settings_for_tools().tool_profile
    except Exception:  # noqa: BLE001 - never fail registration over config
        _profile = "all"
    if _profile not in PROFILE_NAMES:
        pass
    _enabled = resolve_profile(_profile)

    def tool(*, name: str, description: str):
        """Register a tool with FastMCP only if the active profile includes it.

        Every registered tool is wrapped with structured per-call logging and
        gains an optional ``workflow_run_id`` argument (injected here, so no
        per-tool signature edits are needed).
        """
        if name.removeprefix("presto.") in _enabled:
            base_tool = mcp.tool(name=name, description=description)
            short_name = name.removeprefix("presto.")

            def _decorate(fn):
                # eval_str=True resolves the string annotations produced by
                # `from __future__ import annotations`, so the augmented
                # signature carries real types (FastMCP needs them concrete).
                orig_sig = inspect.signature(fn, eval_str=True)
                new_sig = orig_sig.replace(
                    parameters=[*orig_sig.parameters.values(), _WORKFLOW_RUN_ID_PARAM]
                )

                @functools.wraps(fn)
                async def _wrapped(*args, **kwargs):
                    workflow_run_id = kwargs.pop("workflow_run_id", None)
                    ctx = ToolCallContext(
                        short_name,
                        workflow_run_id=workflow_run_id,
                        input_summary=summarize_args(kwargs),
                    )
                    try:
                        result = await fn(*args, **kwargs)
                    except Exception as exc:
                        ctx.finish_error(exc)
                        raise
                    ctx.finish_ok(result)
                    return result

                _wrapped.__signature__ = new_sig
                resolved: dict[str, object] = {
                    p_name: p.annotation
                    for p_name, p in new_sig.parameters.items()
                    if p.annotation is not inspect.Parameter.empty
                }
                if new_sig.return_annotation is not inspect.Signature.empty:
                    resolved["return"] = new_sig.return_annotation
                _wrapped.__annotations__ = resolved
                return base_tool(_wrapped)

            return _decorate

        def _skip(fn):  # tool filtered out by PRESTO_TOOL_PROFILE
            return fn

        return _skip

    # --- Tools ---------------------------------------------------------------------


    @tool(
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
        background: _BackgroundParam = False,
    ) -> ToolRunResult[ReadfileMetadata]:
        return await asyncio.to_thread(
            run_readfile,
            input_file,
            backend=_backend_for_tools(),
            settings=_settings_for_tools(),
            background=background,
        )


    @tool(
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
        background: _BackgroundParam = False,
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


    @tool(
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
        background: _BackgroundParam = False,
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


    @tool(
        name="presto.prepdata",
        description=(
            "Run PRESTO 'prepdata' inside Docker to dedisperse one DM trial into a "
            "single-precision .dat time series (+ .inf header). Optionally accepts "
            "a mask_file (either relative to DATA_DIR or a "
            "'<run_id>/artifacts/<file>.mask' from a prior rfifind run). "
            "Input path is relative to DATA_DIR."
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
                description=(
                    "Optional rfifind .mask file. Either a path relative to "
                    "DATA_DIR or '<run_id>/artifacts/<file>.mask' from a prior "
                    "rfifind run (companion .inf/.bytemask/.rfi/.stats files "
                    "must live next to it; both layouts work)."
                ),
            ),
        ] = None,
        background: _BackgroundParam = False,
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


    @tool(
        name="presto.ddplan",
        description=(
            "Run PRESTO 'DDplan.py' inside Docker to compute an optimal DM-trial "
            "plan. Returns a list of passes (low_dm, dm_step, num_dms, downsamp) "
            "for use with presto.prepsubband. Two modes: (a) parametric — give "
            "freq_mhz/bw_mhz/num_channels/sample_time_us explicitly; (b) supply "
            "input_file (a raw filterbank/PSRFITS path relative to DATA_DIR, or a "
            "'<run_id>/artifacts/<file>') so DDplan.py infers the observation "
            "parameters from it. Any explicit params override file-derived "
            "values. write_dedisp_script=true emits a dedisp_*.py script and "
            "requires input_file (capability-gated against DDplan.py -h)."
        ),
    )
    async def presto_ddplan(
        dm_low: Annotated[float, Field(ge=0.0, le=10_000.0, description="Lowest DM to plan.")],
        dm_high: Annotated[float, Field(ge=0.0, le=10_000.0, description="Highest DM to plan.")],
        freq_mhz: Annotated[
            float | None,
            Field(default=None, gt=0.0, description="Center frequency (MHz)."),
        ] = None,
        bw_mhz: Annotated[
            float | None,
            Field(default=None, gt=0.0, description="Total bandwidth (MHz)."),
        ] = None,
        num_channels: Annotated[
            int | None,
            Field(default=None, ge=1, le=4096, description="Number of frequency channels."),
        ] = None,
        sample_time_us: Annotated[
            float | None,
            Field(default=None, gt=0.0, description="Native sample time in microseconds."),
        ] = None,
        num_subbands: Annotated[
            int | None,
            Field(default=None, ge=1, le=4096, description="Optional number of subbands."),
        ] = None,
        input_file: Annotated[
            str | None,
            Field(
                default=None,
                description=(
                    "Optional raw filterbank/PSRFITS file. Either relative to "
                    "DATA_DIR or '<run_id>/artifacts/<file>'. Mounted read-only "
                    "and appended as DDplan.py's positional argument."
                ),
            ),
        ] = None,
        write_dedisp_script: Annotated[
            bool,
            Field(
                default=False,
                description="Emit a dedisp_*.py script (DDplan.py -w). Requires input_file.",
            ),
        ] = False,
        output_prefix: Annotated[
            str | None,
            Field(default=None, description="Output filename prefix. Defaults to 'ddplan'."),
        ] = None,
        background: _BackgroundParam = False,
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
            input_file=input_file,
            write_dedisp_script=write_dedisp_script,
            output_prefix=output_prefix,
            settings=_settings_for_tools(),
            background=background,
        )


    @tool(
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
            Field(
                default=None,
                description=(
                    "Optional rfifind .mask file. Either relative to DATA_DIR "
                    "or '<run_id>/artifacts/<file>.mask' from a prior rfifind run."
                ),
            ),
        ] = None,
        background: _BackgroundParam = False,
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


    @tool(
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
        background: _BackgroundParam = False,
    ) -> ToolRunResult[RealfftResult]:
        return await asyncio.to_thread(
            run_realfft,
            input_file,
            backend=_backend_for_tools(),
            settings=_settings_for_tools(),
            background=background,
        )


    @tool(
        name="presto.accelsearch",
        description=(
            "Run PRESTO 'accelsearch' inside Docker for Fourier / acceleration "
            "candidate search on a .fft (from a prior realfft run). Produces "
            "ACCEL_<zmax> + .txtcand artifacts and a typed top-N candidate list. "
            "input_file is interpreted relative to RUNS_DIR. Advanced flags "
            "(wmax jerk search, sigma cutoff, ncpus) are capability-checked "
            "against 'accelsearch -h' first; if the image's accelsearch lacks a "
            "requested flag the call fails with a clear error rather than "
            "silently dropping it. candidate_limit only caps the parsed top-N."
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
        wmax: Annotated[
            int | None,
            Field(
                default=None,
                ge=0,
                le=1200,
                description="Max Fourier w for a jerk search (image-dependent flag).",
            ),
        ] = None,
        sigma: Annotated[
            float | None,
            Field(
                default=None,
                ge=1.0,
                le=30.0,
                description="Candidate sigma cutoff (image-dependent flag).",
            ),
        ] = None,
        ncpus: Annotated[
            int | None,
            Field(
                default=None,
                ge=1,
                le=64,
                description="OpenMP CPU count (image-dependent flag).",
            ),
        ] = None,
        candidate_limit: Annotated[
            int | None,
            Field(
                default=None,
                ge=1,
                le=1000,
                description="Cap the parsed top_candidates list (does not change the search).",
            ),
        ] = None,
        background: _BackgroundParam = False,
    ) -> ToolRunResult[AccelsearchResult]:
        return await asyncio.to_thread(
            run_accelsearch,
            input_file,
            backend=_backend_for_tools(),
            zmax=zmax,
            numharm=numharm,
            wmax=wmax,
            sigma=sigma,
            ncpus=ncpus,
            candidate_limit=candidate_limit,
            settings=_settings_for_tools(),
            background=background,
        )


    @tool(
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
        background: _BackgroundParam = False,
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


    @tool(
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
        background: _BackgroundParam = False,
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


    @tool(
        name="presto.get_toas",
        description=(
            "Run PRESTO 'get_TOAs.py' inside Docker to compute Times of Arrival "
            "from a folded .pfd plus either a Gaussian template file or a "
            "numeric Gaussian FWHM width. pfd_file is '<run_id>/artifacts/"
            "<file>.pfd' relative to RUNS_DIR; template_file is relative to "
            "DATA_DIR when provided. Returns TEMPO/TEMPO2 TOA lines."
        ),
    )
    async def presto_get_toas(
        pfd_file: Annotated[
            str,
            Field(description="<run_id>/artifacts/<file>.pfd relative to RUNS_DIR."),
        ],
        template_file: Annotated[
            str | None,
            Field(
                default=None,
                description="Gaussian template (.gaussians/.template) relative to DATA_DIR.",
            ),
        ] = None,
        num_subints: Annotated[
            int,
            Field(default=1, ge=1, le=4096, description="Number of TOAs / time parts (-n)."),
        ] = 1,
        num_subbands: Annotated[
            int,
            Field(default=1, ge=1, le=4096, description="Number of frequency subbands (-s)."),
        ] = 1,
        gaussian_width: Annotated[
            float | None,
            Field(
                default=None,
                gt=0.0,
                le=1.0,
                description=(
                    "Optional Gaussian FWHM width for PRESTO -g. Provide exactly "
                    "one of template_file or gaussian_width."
                ),
            ),
        ] = None,
        background: _BackgroundParam = False,
    ) -> ToolRunResult[GetTOAsResult]:
        return await asyncio.to_thread(
            run_get_toas,
            pfd_file,
            template_file,
            backend=_backend_for_tools(),
            num_subints=num_subints,
            num_subbands=num_subbands,
            gaussian_width=gaussian_width,
            settings=_settings_for_tools(),
            background=background,
        )


    @tool(
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
        background: _BackgroundParam = False,
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


    @tool(
        name="presto.rrattrap",
        description=(
            "[experimental / image-dependent] Run PRESTO 'rrattrap.py' inside Docker "
            "to group single-pulse events "
            "from one or more .singlepulse files (from prior single_pulse_search "
            "runs) plus the .inf header. Writes groups.txt into the run's "
            "artifacts/. All inputs are '<run_id>/artifacts/...' relative to RUNS_DIR. "
            "Requires `rrattrap.py` in PATH and `presto.singlepulse` importable "
            "inside the configured PRESTO image."
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
        background: _BackgroundParam = False,
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


    @tool(
        name="presto.make_spd",
        description=(
            "Run PRESTO 'make_spd.py' inside Docker to produce single-pulse "
            "diagnostic .spd files. Reads a rrattrap groups.txt + raw "
            "filterbank/PSRFITS + .singlepulse files (and optional rfifind .mask). "
            "raw_file is relative to DATA_DIR; groups_file and singlepulse_files "
            "are '<run_id>/artifacts/...' relative to RUNS_DIR; mask_file may be "
            "either form."
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
            Field(
                default=None,
                description=(
                    "Optional rfifind .mask file. Either relative to DATA_DIR "
                    "or '<run_id>/artifacts/<file>.mask' from a prior rfifind run."
                ),
            ),
        ] = None,
        output_prefix: Annotated[
            str | None,
            Field(default=None, description="Output basename for .spd files. Defaults to 'spd'."),
        ] = None,
        apply_mask: Annotated[
            bool,
            Field(default=False, description="Pass --mask to enable masking (requires mask_file)."),
        ] = False,
        background: _BackgroundParam = False,
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


    @tool(
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
        background: _BackgroundParam = False,
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


    @tool(
        name="presto.single_pulse_diagnostic",
        description=(
            "Run PRESTO's canonical single-pulse diagnostic chain end-to-end: "
            "single_pulse_search -> rrattrap -> make_spd -> plot_spd. Each stage "
            "runs as a separate PRESTO invocation with its own run_id and manifest. "
            "Returns a typed result enumerating per-stage run_ids, the surviving "
            ".spd files (PRESTO's authoritative single-pulse artifact), and the "
            "plot_spd PNGs. Prefer this over the MCP-side waterfaller quicklook "
            "when the goal is a canonical single-pulse diagnostic. The workflow "
            "short-circuits on the first failing stage."
        ),
    )
    async def presto_single_pulse_diagnostic(
        dat_files: Annotated[
            list[str],
            Field(
                description=(
                    "List of <run_id>/artifacts/<file>.dat paths from "
                    "prepdata/prepsubband."
                ),
            ),
        ],
        inf_file: Annotated[
            str,
            Field(description="<run_id>/artifacts/<file>.inf matching the .dat files."),
        ],
        raw_file: Annotated[
            str,
            Field(
                description=(
                    "Original observation; either relative to DATA_DIR or "
                    "'<run_id>/artifacts/<file>' (auto-detected)."
                ),
            ),
        ],
        mask_file: Annotated[
            str | None,
            Field(
                default=None,
                description=(
                    "Optional rfifind .mask file. Either relative to DATA_DIR or "
                    "'<run_id>/artifacts/<file>.mask' from a prior rfifind run. "
                    "Required when apply_mask is true."
                ),
            ),
        ] = None,
        apply_mask: Annotated[
            bool,
            Field(
                default=False,
                description="Forwarded to make_spd --mask (requires mask_file).",
            ),
        ] = False,
        threshold: Annotated[
            float,
            Field(
                default=5.0,
                description="single_pulse_search sigma threshold.",
            ),
        ] = 5.0,
        max_width_s: Annotated[
            float,
            Field(
                default=0.1,
                description="single_pulse_search maximum pulse width (s).",
            ),
        ] = 0.1,
        min_group: Annotated[
            int | None,
            Field(
                default=None,
                description="rrattrap minimum group size.",
            ),
        ] = None,
        use_dm_plan: Annotated[
            bool,
            Field(
                default=False,
                description="rrattrap --use-DMplan flag.",
            ),
        ] = False,
        just_waterfall: Annotated[
            bool,
            Field(
                default=False,
                description="Forwarded to plot_spd --just-waterfall.",
            ),
        ] = False,
        max_spd_plots: Annotated[
            int,
            Field(
                default=10,
                ge=0,
                le=1000,
                description=(
                    "Maximum number of .spd files to plot (each plot is its own "
                    "PRESTO invocation). 0 skips the plot_spd stage entirely."
                ),
            ),
        ] = 10,
    ) -> ToolRunResult[SinglePulseDiagnosticResult]:
        def _go() -> ToolRunResult[SinglePulseDiagnosticResult]:
            result, status = run_single_pulse_diagnostic(
                dat_files=dat_files,
                inf_file=inf_file,
                raw_file=raw_file,
                backend=_backend_for_tools(),
                mask_file=mask_file,
                apply_mask=apply_mask,
                threshold=threshold,
                max_width_s=max_width_s,
                min_group=min_group,
                use_dm_plan=use_dm_plan,
                just_waterfall=just_waterfall,
                max_spd_plots=max_spd_plots,
                settings=_settings_for_tools(),
            )
            # The composite tool has no single run_id of its own; surface the
            # first stage's run_id when available so observability can still
            # cross-link, and aggregate per-stage errors into the envelope.
            first_run = result.stages[0].run_id if result.stages else ""
            errors = [
                f"{s.stage}({s.run_id}): {s.error}"
                for s in result.stages
                if s.error
            ]
            return ToolRunResult[SinglePulseDiagnosticResult](
                run_id=first_run,
                status=status,
                result=result,
                manifest_uri=(
                    f"presto://runs/{first_run}/manifest" if first_run else ""
                ),
                stdout_uri=(
                    f"presto://runs/{first_run}/stdout" if first_run else ""
                ),
                stderr_uri=(
                    f"presto://runs/{first_run}/stderr" if first_run else ""
                ),
                artifact_uris=[],
                error="; ".join(errors) or None,
            )

        return await asyncio.to_thread(_go)


    @tool(
        name="presto.waterfaller",
        description=(
            "Run PRESTO 'waterfaller.py' inside Docker to render a dynamic-spectrum "
            "(waterfall) image around a candidate (start_s, duration_s, dm) for a "
            "raw filterbank/PSRFITS file under DATA_DIR. Optional mask_file is "
            "either relative to DATA_DIR or '<run_id>/artifacts/<file>.mask' from "
            "a prior rfifind run. Optional colour_map forwards to PRESTO "
            "--colour-map (matplotlib colormap name). "
            "Requires the PRESTO image's PNG-tagged variant "
            "to write the figure into the working directory."
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
            Field(
                default=None,
                description=(
                    "Optional rfifind .mask file. Either relative to DATA_DIR "
                    "or '<run_id>/artifacts/<file>.mask' from a prior rfifind run."
                ),
            ),
        ] = None,
        colour_map: Annotated[
            str | None,
            Field(
                default=None,
                description=(
                    "Optional matplotlib colormap name passed to PRESTO "
                    "as --colour-map (examples: viridis, plasma, gist_yarg)."
                ),
            ),
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
        background: _BackgroundParam = False,
    ) -> ToolRunResult[WaterfallerResult]:
        return await asyncio.to_thread(
            run_waterfaller,
            input_file,
            backend=_backend_for_tools(),
            start_s=start_s,
            duration_s=duration_s,
            dm=dm,
            mask_file=mask_file,
            colour_map=colour_map,
            nsub=nsub,
            nbins=nbins,
            downsamp=downsamp,
            settings=_settings_for_tools(),
            background=background,
        )


    @tool(
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


    @tool(
        name="presto.get_run_manifest",
        description="Return the full manifest JSON for a given run_id.",
    )
    async def presto_get_run_manifest(
        run_id: Annotated[str, Field(description="A run_id from presto.list_runs.")],
    ) -> RunManifest:
        return await asyncio.to_thread(
            list_runs_tool.get_run_manifest, run_id, settings=_settings_for_tools()
        )



    # --- Additional PRESTO tools (data prep / RFI / fold QC / advanced) -----------


    @tool(
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
        background: _BackgroundParam = False,
    ) -> ToolRunResult[Psrfits2FilResult]:
        return await asyncio.to_thread(
            run_psrfits2fil,
            input_file,
            backend=_backend_for_tools(),
            output_prefix=output_prefix,
            settings=_settings_for_tools(),
            background=background,
        )


    @tool(
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
        background: _BackgroundParam = False,
    ) -> ToolRunResult[DownsampleFilterbankResult]:
        return await asyncio.to_thread(
            run_downsample_filterbank,
            input_file,
            backend=_backend_for_tools(),
            factor=factor,
            settings=_settings_for_tools(),
            background=background,
        )


    @tool(
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
        background: _BackgroundParam = False,
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


    @tool(
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
        background: _BackgroundParam = False,
    ) -> ToolRunResult[RfifindStatsResult]:
        return await asyncio.to_thread(
            run_rfifind_stats,
            stats_file,
            backend=_backend_for_tools(),
            mask_file=mask_file,
            settings=_settings_for_tools(),
            background=background,
        )


    @tool(
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
        background: _BackgroundParam = False,
    ) -> ToolRunResult[Pfd2PngResult]:
        return await asyncio.to_thread(
            run_pfd2png,
            pfd_file,
            backend=_backend_for_tools(),
            settings=_settings_for_tools(),
            background=background,
        )

    @tool(
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
        background: _BackgroundParam = False,
    ) -> ToolRunResult[MakeZaplistResult]:
        return await asyncio.to_thread(
            run_makezaplist,
            input_file,
            backend=_backend_for_tools(),
            settings=_settings_for_tools(),
            background=background,
        )


    @tool(
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
        background: _BackgroundParam = False,
    ) -> ToolRunResult[WeightsToIgnorechanResult]:
        return await asyncio.to_thread(
            run_weights_to_ignorechan,
            weights_file,
            backend=_backend_for_tools(),
            threshold=threshold,
            settings=_settings_for_tools(),
            background=background,
        )

    @tool(
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
        background: _BackgroundParam = False,
    ) -> ToolRunResult[SumProfilesResult]:
        return await asyncio.to_thread(
            run_sum_profiles,
            profile_files,
            backend=_backend_for_tools(),
            settings=_settings_for_tools(),
            background=background,
        )


    @tool(
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
        background: _BackgroundParam = False,
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


    @tool(
        name="presto.stacksearch",
        description=(
            "[experimental / image-dependent] Run PRESTO 'stacksearch.py' inside "
            "Docker to stack-search several .fft files (each from a prior realfft "
            "run) and boost weak periodic signals. Requires stacksearch.py in the "
            "PRESTO image — a readiness preflight fails fast with a controlled "
            "error otherwise. Verify with presto.validate_environment "
            "(include_tool_readiness=true) first. Inputs are "
            "'<run_id>/artifacts/<file>.fft' relative to RUNS_DIR."
        ),
    )
    async def presto_stacksearch(
        fft_files: Annotated[
            list[str],
            Field(
                description="List of <run_id>/artifacts/<file>.fft (min 2).",
                min_length=2,
                max_length=256,
            ),
        ],
        background: _BackgroundParam = False,
    ) -> ToolRunResult[StackSearchResult]:
        return await asyncio.to_thread(
            run_stacksearch,
            fft_files,
            backend=_backend_for_tools(),
            settings=_settings_for_tools(),
            background=background,
        )


    @tool(
        name="presto.simple_zapbirds",
        description=(
            "[experimental / image-dependent] Run PRESTO 'simple_zapbirds.py' "
            "inside Docker to zap known interference ('birdies') out of a .fft. "
            "The source .fft (a prior realfft artifact) is COPIED into the new "
            "run's artifacts/ and the zap runs on the copy — the source is never "
            "modified in place. fft_file is '<run_id>/artifacts/<file>.fft' "
            "relative to RUNS_DIR; birds_file is relative to DATA_DIR or a "
            "'<run_id>/artifacts/<file>'. Verify availability with "
            "presto.validate_environment first."
        ),
    )
    async def presto_simple_zapbirds(
        fft_file: Annotated[
            str,
            Field(description="<run_id>/artifacts/<file>.fft relative to RUNS_DIR."),
        ],
        birds_file: Annotated[
            str,
            Field(
                description=(
                    "Birds/zap file: relative to DATA_DIR or "
                    "'<run_id>/artifacts/<file>'."
                ),
            ),
        ],
        background: _BackgroundParam = False,
    ) -> ToolRunResult[SimpleZapbirdsResult]:
        return await asyncio.to_thread(
            run_simple_zapbirds,
            fft_file,
            birds_file,
            backend=_backend_for_tools(),
            settings=_settings_for_tools(),
            background=background,
        )


    @tool(
        name="presto.compare_periods",
        description=(
            "Utility tool (no Docker): cross-check a candidate spin period "
            "against one or more pulsar ephemeris (.par) files. Reports matches "
            "to each pulsar's period and its harmonics / subharmonics with a "
            "confidence label (exact/near/weak). Use this for known-pulsar "
            "cross-checks — it never asserts a scientific detection. par_files "
            "are relative to DATA_DIR or '<run_id>/artifacts/<file>'."
        ),
    )
    async def presto_compare_periods(
        period_ms: Annotated[
            float,
            Field(gt=0.0, description="Candidate spin period in milliseconds."),
        ],
        par_files: Annotated[
            list[str],
            Field(
                description="Ephemeris .par files (DATA_DIR or run artifacts).",
                min_length=1,
                max_length=256,
            ),
        ],
        tolerance: Annotated[
            float | None,
            Field(
                default=None,
                gt=0.0,
                le=0.5,
                description="Relative match tolerance (default 1e-3).",
            ),
        ] = None,
        max_harmonic: Annotated[
            int | None,
            Field(
                default=None,
                ge=1,
                le=64,
                description="Highest harmonic / subharmonic to test (default 8).",
            ),
        ] = None,
    ) -> ComparePeriodsResult:
        return await asyncio.to_thread(
            run_compare_periods,
            period_ms,
            par_files,
            tolerance=tolerance,
            max_harmonic=max_harmonic,
            settings=_settings_for_tools(),
        )


    @tool(
        name="presto.binary_info",
        description=(
            "Utility tool (no Docker): summarise the orbital parameters of a "
            "binary-pulsar ephemeris (.par) file — orbital period, projected "
            "semi-major axis, eccentricity — and derive the line-of-sight "
            "velocity amplitude plus the Doppler-smeared spin period / frequency "
            "range an acceleration search must cover. par_file is relative to "
            "DATA_DIR or '<run_id>/artifacts/<file>'."
        ),
    )
    async def presto_binary_info(
        par_file: Annotated[
            str,
            Field(description="Ephemeris .par file (DATA_DIR or run artifact)."),
        ],
        inf_file: Annotated[
            str | None,
            Field(
                default=None,
                description="Optional companion .inf file (DATA_DIR or run artifact).",
            ),
        ] = None,
    ) -> BinaryInfoResult:
        return await asyncio.to_thread(
            run_binary_info,
            par_file,
            inf_file=inf_file,
            settings=_settings_for_tools(),
        )


    @tool(
        name="presto.compile_candidate_report_pdf",
        description=(
            "Utility tool (no Docker): bundle PNG/JPG plot artifacts from one or "
            "more runs into a single reviewable PDF, written to a fresh "
            "runs/<run_id>/artifacts/ directory. Reads only artifacts under "
            "runs/ (never data/, never absolute paths). Corrupt images are "
            "listed in skipped_artifacts and skipped; duplicate images (same "
            "content) are collapsed; page order is deterministic. Provide "
            "run_ids and/or explicit artifact_paths."
        ),
    )
    async def presto_compile_candidate_report_pdf(
        run_ids: Annotated[
            list[str] | None,
            Field(
                default=None,
                description="Run IDs whose artifacts/ images should be included.",
            ),
        ] = None,
        artifact_paths: Annotated[
            list[str] | None,
            Field(
                default=None,
                description="Explicit '<run_id>/artifacts/<file>' image paths.",
            ),
        ] = None,
        include_patterns: Annotated[
            list[str] | None,
            Field(
                default=None,
                description="Glob patterns to include. Defaults to *.png/*.jpg/*.jpeg.",
            ),
        ] = None,
        title: Annotated[
            str | None,
            Field(default=None, description="Optional title page text."),
        ] = None,
        output_prefix: Annotated[
            str | None,
            Field(default=None, description="PDF filename prefix. Defaults to 'candidate_report'."),
        ] = None,
        sort_by: Annotated[
            Literal["run_id_name", "mtime", "name"],
            Field(default="run_id_name", description="Deterministic page ordering."),
        ] = "run_id_name",
    ) -> ToolRunResult[CandidateReportPdfResult]:
        return await asyncio.to_thread(
            run_compile_candidate_report_pdf,
            run_ids=run_ids,
            artifact_paths=artifact_paths,
            include_patterns=include_patterns,
            title=title,
            output_prefix=output_prefix,
            sort_by=sort_by,
            settings=_settings_for_tools(),
        )


    @tool(
        name="presto.pfdzap",
        description=(
            "[experimental] Run PRESTO 'pfdzap.py' inside Docker to apply strict "
            "interval/channel zapping to a .pfd. zap_commands are strict "
            "'<low>:<high>' integer tokens (max 512); arbitrary shell input is "
            "rejected. The source .pfd is copied into the new run's artifacts/ "
            "and zapped there. pfd_file is '<run_id>/artifacts/<file>.pfd' "
            "relative to RUNS_DIR. Verify availability with "
            "presto.validate_environment first."
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
                description="Strict '<low>:<high>' integer zap tokens.",
                min_length=1,
                max_length=512,
            ),
        ],
        output_prefix: Annotated[
            str | None,
            Field(default=None, description="Output filename prefix. Defaults to 'pfdzap'."),
        ] = None,
        background: _BackgroundParam = False,
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


    @tool(
        name="presto.fourier_fold",
        description=(
            "[experimental] Run PRESTO 'fourier_fold.py' inside Docker to fold a "
            ".fft at a known candidate from its complex amplitudes (no full "
            "temporal fold). Provide exactly one of period_seconds or "
            "frequency_hz; dm is optional. fft_file is "
            "'<run_id>/artifacts/<file>.fft' relative to RUNS_DIR (from a prior "
            "realfft run). Verify availability with presto.validate_environment "
            "first."
        ),
    )
    async def presto_fourier_fold(
        fft_file: Annotated[
            str,
            Field(description="<run_id>/artifacts/<file>.fft relative to RUNS_DIR."),
        ],
        period_seconds: Annotated[
            float | None,
            Field(
                default=None,
                gt=0.0,
                le=60.0,
                description=(
                    "Candidate spin period in seconds. Provide exactly one of "
                    "period_seconds or frequency_hz."
                ),
            ),
        ] = None,
        frequency_hz: Annotated[
            float | None,
            Field(
                default=None,
                gt=0.0,
                le=1.0e9,
                description=(
                    "Candidate spin frequency in Hz. Provide exactly one of "
                    "period_seconds or frequency_hz."
                ),
            ),
        ] = None,
        dm: Annotated[
            float | None,
            Field(
                default=None,
                ge=0.0,
                le=10_000.0,
                description="Optional dispersion measure (pc cm^-3).",
            ),
        ] = None,
        background: _BackgroundParam = False,
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


    # --- Utility tools (no PRESTO execution) --------------------------------------


    @tool(
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


    @tool(
        name="presto.validate_environment",
        description=(
            "Structured local-environment diagnostic. Checks settings, data/runs/"
            "outputs/logs directories, docker CLI presence and (optionally) the "
            "PRESTO image, plus policy sanity (cpus, memory_mb, timeout_s). When "
            "include_tool_readiness=true it also probes the PRESTO image for each "
            "tool's binaries / python modules and reports per-tool readiness "
            "(e.g. presto.rrattrap needs the importable module presto.singlepulse). "
            "Never executes real PRESTO work. Each check returns OK/WARN/ERROR/"
            "UNKNOWN with remediation. Call this first in any session."
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
        include_tool_readiness: Annotated[
            bool,
            Field(
                default=True,
                description=(
                    "If true, probe the PRESTO image with lightweight Docker "
                    "commands and report per-tool readiness. Results are cached "
                    "per image for ~15 min."
                ),
            ),
        ] = True,
        force_refresh: Annotated[
            bool,
            Field(
                default=False,
                description="If true, bypass the runtime-capability cache.",
            ),
        ] = False,
    ) -> ValidateEnvironmentResult:
        return await asyncio.to_thread(
            run_validate_environment,
            check_image=check_image,
            include_tool_readiness=include_tool_readiness,
            force_refresh=force_refresh,
            settings=_settings_for_tools(),
        )


    @tool(
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


    @tool(
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


    # --- Modern reporting layer (post-hoc; reads an internal workdir) --------------


    @tool(
        name="presto.export_candidates_csv",
        description=(
            "Export a normalized candidates.csv file containing all candidates found "
            "in a PRESTO run. Use this when the user asks for candidate tables, CSV "
            "files, detections, event lists, or machine-readable candidate outputs. "
            "Reads raw PRESTO outputs (.singlepulse, ACCEL_*, .bestprof, groups.txt) "
            "from runs/<run_id>/ and writes outputs/<new_run_id>/candidates.csv. "
            "Provide run_ids (and/or workdir) identifying the runs to consolidate."
        ),
    )
    async def presto_export_candidates_csv(
        run_ids: Annotated[
            list[str] | None,
            Field(default=None, description="Run IDs whose raw outputs hold candidates."),
        ] = None,
        workdir: Annotated[
            str | None,
            Field(default=None, description="Optional extra workdir path relative to runs/."),
        ] = None,
        input_file: Annotated[
            str | None,
            Field(default=None, description="Original observation path (recorded in the CSV)."),
        ] = None,
    ) -> ReportToolResult:
        return await asyncio.to_thread(
            run_export_candidates_csv,
            run_ids=run_ids,
            workdir=workdir,
            input_file=input_file,
            settings=_settings_for_tools(),
        )


    @tool(
        name="presto.generate_summary_json",
        description=(
            "Generate a structured summary.json file with observation metadata, "
            "PRESTO workflow information, candidate counts, RFI/data quality summary, "
            "warnings, and errors. Reads runs/<run_id>/ and writes "
            "outputs/<new_run_id>/summary.json. Conservative: never assumes the file "
            "contains a pulsar/FRB/RRAT."
        ),
    )
    async def presto_generate_summary_json(
        run_ids: Annotated[
            list[str] | None,
            Field(default=None, description="Run IDs to summarize."),
        ] = None,
        workdir: Annotated[
            str | None,
            Field(default=None, description="Optional extra workdir path relative to runs/."),
        ] = None,
        input_file: Annotated[
            str | None,
            Field(default=None, description="Original observation path (recorded in summary)."),
        ] = None,
    ) -> ReportToolResult:
        return await asyncio.to_thread(
            run_generate_summary_json,
            run_ids=run_ids,
            workdir=workdir,
            input_file=input_file,
            settings=_settings_for_tools(),
        )


    @tool(
        name="presto.generate_visual_artifacts",
        description=(
            "Generate and publish PNG visual diagnostics from PRESTO plots and "
            "MCP-generated visualizations. Use this when the user asks for plots, "
            "images, diagnostics, visual inspection, or PNG artifacts. Collects "
            "raster images, converts .ps/.eps via Ghostscript when available, and "
            "writes outputs/<new_run_id>/visuals/ + thumbnails/."
        ),
    )
    async def presto_generate_visual_artifacts(
        run_ids: Annotated[
            list[str] | None,
            Field(default=None, description="Run IDs whose plots should be published."),
        ] = None,
        workdir: Annotated[
            str | None,
            Field(default=None, description="Optional extra workdir path relative to runs/."),
        ] = None,
    ) -> ReportToolResult:
        return await asyncio.to_thread(
            run_generate_visual_artifacts,
            run_ids=run_ids,
            workdir=workdir,
            settings=_settings_for_tools(),
        )


    @tool(
        name="presto.generate_candidate_waterfalls",
        description=(
            "QUICKLOOK ONLY — bulk-render per-candidate waterfall PNGs/PDFs for fast "
            "triage of many events. Event selection (top-N / DM / SNR / time window) "
            "is MCP-side, NOT PRESTO's canonical single-pulse diagnostic semantics. "
            "For a canonical single-pulse diagnostic of a specific candidate, prefer "
            "the make_spd -> plot_spd chain (.spd file is PRESTO's authoritative "
            "single-pulse artifact). Rendering runs through the containerized PRESTO "
            "waterfaller. Defaults: colour map inferno, PNG on, PDF off, top-N "
            "selection. input_file is the original observation relative to DATA_DIR."
        ),
    )
    async def presto_generate_candidate_waterfalls(
        input_file: Annotated[
            str,
            Field(description="Original observation file relative to DATA_DIR."),
        ],
        run_ids: Annotated[
            list[str] | None,
            Field(default=None, description="Run IDs whose candidates drive the waterfalls."),
        ] = None,
        workdir: Annotated[
            str | None,
            Field(default=None, description="Optional extra workdir path relative to runs/."),
        ] = None,
        candidate_selection: Annotated[
            Literal["one", "top_n", "all"],
            Field(default="top_n", description="Which candidates to render."),
        ] = "top_n",
        top_n: Annotated[
            int,
            Field(default=10, ge=1, le=1000, description="Count for top_n selection."),
        ] = 10,
        candidate_id: Annotated[
            str | None,
            Field(default=None, description="Candidate id for candidate_selection='one'."),
        ] = None,
        min_snr: Annotated[
            float | None,
            Field(default=None, description="Keep candidates with SNR/sigma >= this."),
        ] = None,
        min_dm: Annotated[
            float | None,
            Field(default=None, description="Keep candidates with DM >= this."),
        ] = None,
        max_dm: Annotated[
            float | None,
            Field(default=None, description="Keep candidates with DM <= this."),
        ] = None,
        time_window_sec: Annotated[
            float | None,
            Field(default=None, gt=0.0, le=600.0, description="Waterfall window length (s)."),
        ] = None,
        colour_map: Annotated[
            str | None,
            Field(
                default=None,
                description=(
                    "Matplotlib colormap name (canonical, matches PRESTO "
                    "--colour-map). Defaults to 'inferno' when both this and the "
                    "deprecated 'color_map' alias are unset."
                ),
            ),
        ] = None,
        color_map: Annotated[
            str | None,
            Field(
                default=None,
                description="Deprecated alias for colour_map (kept for back-compat).",
            ),
        ] = None,
        export_png: Annotated[
            bool,
            Field(default=True, description="Publish per-candidate PNG waterfalls."),
        ] = True,
        export_pdf: Annotated[
            bool,
            Field(default=False, description="Also publish per-candidate PDF waterfalls."),
        ] = False,
    ) -> ReportToolResult:
        return await asyncio.to_thread(
            run_generate_candidate_waterfalls,
            run_ids=run_ids,
            workdir=workdir,
            input_file=input_file,
            settings=_settings_for_tools(),
            backend=_backend_for_tools(),
            candidate_selection=candidate_selection,
            top_n=top_n,
            candidate_id=candidate_id,
            min_snr=min_snr,
            min_dm=min_dm,
            max_dm=max_dm,
            time_window_sec=time_window_sec,
            colour_map=colour_map,
            color_map=color_map,
            export_png=export_png,
            export_pdf=export_pdf,
        )


    @tool(
        name="presto.generate_report_html",
        description=(
            "Generate a modern offline HTML report summarizing observation metadata, "
            "PRESTO tools executed, candidates, RFI/data quality, visual diagnostics, "
            "waterfalls, and downloadable artifacts. Plain HTML + embedded CSS, no "
            "external CDNs — works fully offline. Writes outputs/<new_run_id>/"
            "report.html alongside summary.json, candidates.csv and visuals."
        ),
    )
    async def presto_generate_report_html(
        run_ids: Annotated[
            list[str] | None,
            Field(default=None, description="Run IDs to report on."),
        ] = None,
        workdir: Annotated[
            str | None,
            Field(default=None, description="Optional extra workdir path relative to runs/."),
        ] = None,
        input_file: Annotated[
            str | None,
            Field(default=None, description="Original observation path (recorded in report)."),
        ] = None,
        self_contained: Annotated[
            bool,
            Field(default=False, description="Base64-embed images (larger, single-file)."),
        ] = False,
        title: Annotated[
            str | None,
            Field(default=None, description="Optional report title."),
        ] = None,
    ) -> ReportToolResult:
        return await asyncio.to_thread(
            run_generate_report_html,
            run_ids=run_ids,
            workdir=workdir,
            input_file=input_file,
            settings=_settings_for_tools(),
            self_contained=self_contained,
            title=title,
        )


    @tool(
        name="presto.generate_report_markdown",
        description=(
            "Generate a lightweight Markdown report summarizing the PRESTO run, "
            "candidates, metadata, warnings, and artifact links. Writes "
            "outputs/<new_run_id>/report.md."
        ),
    )
    async def presto_generate_report_markdown(
        run_ids: Annotated[
            list[str] | None,
            Field(default=None, description="Run IDs to report on."),
        ] = None,
        workdir: Annotated[
            str | None,
            Field(default=None, description="Optional extra workdir path relative to runs/."),
        ] = None,
        input_file: Annotated[
            str | None,
            Field(default=None, description="Original observation path (recorded in report)."),
        ] = None,
        title: Annotated[
            str | None,
            Field(default=None, description="Optional report title."),
        ] = None,
    ) -> ReportToolResult:
        return await asyncio.to_thread(
            run_generate_report_markdown,
            run_ids=run_ids,
            workdir=workdir,
            input_file=input_file,
            settings=_settings_for_tools(),
            title=title,
        )


    @tool(
        name="presto.generate_modern_report_bundle",
        description=(
            "Generate a complete modern reporting bundle for a PRESTO run, including "
            "summary.json, candidates.csv, PNG visuals, thumbnails, waterfall PDFs, "
            "report.html, and report.md according to the requested artifact policy. "
            "Preferred tool when the user asks for a modern report, an HTML report, a "
            "dashboard, a full reporting bundle, or an astronomer-facing summary. The "
            "LLM sets the wants_* intention flags from the user's request; with no "
            "flag set, the full report bundle is produced. Set wants_waterfalls / "
            "input_file to render per-candidate waterfalls (containerized)."
        ),
    )
    async def presto_generate_modern_report_bundle(
        run_ids: Annotated[
            list[str] | None,
            Field(default=None, description="Run IDs to bundle into the report."),
        ] = None,
        workdir: Annotated[
            str | None,
            Field(default=None, description="Optional extra workdir path relative to runs/."),
        ] = None,
        input_file: Annotated[
            str | None,
            Field(default=None, description="Original observation file relative to DATA_DIR."),
        ] = None,
        wants_metadata_only: Annotated[
            bool, Field(default=False, description="Only summary.json.")
        ] = False,
        wants_candidates: Annotated[
            bool, Field(default=False, description="summary.json + candidates.csv.")
        ] = False,
        wants_visuals: Annotated[
            bool, Field(default=False, description="PNG visuals + thumbnails + HTML.")
        ] = False,
        wants_waterfalls: Annotated[
            bool, Field(default=False, description="Per-candidate waterfall PNGs + HTML.")
        ] = False,
        wants_waterfall_pdf: Annotated[
            bool, Field(default=False, description="Also per-candidate waterfall PDFs.")
        ] = False,
        wants_report: Annotated[
            bool, Field(default=False, description="Full modern report bundle.")
        ] = False,
        wants_no_extra_files: Annotated[
            bool,
            Field(default=False, description="Publish only explicitly requested artifacts."),
        ] = False,
        wants_original_presto_outputs: Annotated[
            bool,
            Field(default=False, description="Also publish raw PRESTO files (presto_raw_exports/)."),
        ] = False,
        title: Annotated[
            str | None, Field(default=None, description="Optional report title.")
        ] = None,
        waterfall_cmap: Annotated[
            str, Field(default="inferno", description="Waterfall colormap.")
        ] = "inferno",
        self_contained_html: Annotated[
            bool, Field(default=False, description="Base64-embed images in report.html.")
        ] = False,
        waterfall_selection: Annotated[
            Literal["one", "top_n", "all"],
            Field(default="top_n", description="Waterfall candidate selection."),
        ] = "top_n",
        waterfall_top_n: Annotated[
            int, Field(default=10, ge=1, le=1000, description="Top-N count for waterfalls.")
        ] = 10,
    ) -> ReportToolResult:
        return await asyncio.to_thread(
            run_generate_modern_report_bundle,
            run_ids=run_ids,
            workdir=workdir,
            input_file=input_file,
            settings=_settings_for_tools(),
            backend=_backend_for_tools(),
            wants_metadata_only=wants_metadata_only,
            wants_candidates=wants_candidates,
            wants_visuals=wants_visuals,
            wants_waterfalls=wants_waterfalls,
            wants_waterfall_pdf=wants_waterfall_pdf,
            wants_report=wants_report,
            wants_no_extra_files=wants_no_extra_files,
            wants_original_presto_outputs=wants_original_presto_outputs,
            title=title,
            waterfall_cmap=waterfall_cmap,
            self_contained_html=self_contained_html,
            waterfall_selection=waterfall_selection,
            waterfall_top_n=waterfall_top_n,
        )


