"""Tool entrypoints for the modern reporting layer (7 ``presto.*`` tools).

Each ``run_*`` function builds a narrow :class:`ArtifactPolicy` and delegates to
:func:`presto_mcp.reporting.bundle.generate_bundle`. They publish only modern,
astronomer-facing artifacts into ``outputs/<run_id>/`` — raw PRESTO files stay
in the internal workdir unless raw export is explicitly requested.
"""

from __future__ import annotations

import logging

from ..config import Settings
from ..docker_backend import BackendProtocol
from ..reporting.artifact_policy import route_intention
from ..reporting.bundle import generate_bundle
from ..reporting.schemas import ArtifactPolicy, IntentionFlags, ReportOptions, ReportToolResult

log = logging.getLogger("presto_mcp.tools.reporting")

_ALL_OFF = {
    "export_summary_json": False,
    "export_candidates_csv": False,
    "export_visual_png": False,
    "export_thumbnails": False,
    "export_waterfall_png": False,
    "export_waterfall_pdf": False,
    "export_report_html": False,
    "export_report_markdown": False,
}


def run_export_candidates_csv(
    *,
    run_ids: list[str] | None = None,
    workdir: str | None = None,
    input_file: str | None = None,
    settings: Settings,
) -> ReportToolResult:
    """Export ``candidates.csv`` — every parseable candidate, normalized."""
    policy = ArtifactPolicy(**{**_ALL_OFF, "export_candidates_csv": True})
    return generate_bundle(
        tool_name="export_candidates_csv",
        run_ids=run_ids,
        workdir=workdir,
        input_file=input_file,
        policy=policy,
        options=ReportOptions(),
        settings=settings,
    )


def run_generate_summary_json(
    *,
    run_ids: list[str] | None = None,
    workdir: str | None = None,
    input_file: str | None = None,
    settings: Settings,
) -> ReportToolResult:
    """Generate ``summary.json`` — observation + workflow + candidate summary."""
    policy = ArtifactPolicy(**{**_ALL_OFF, "export_summary_json": True})
    return generate_bundle(
        tool_name="generate_summary_json",
        run_ids=run_ids,
        workdir=workdir,
        input_file=input_file,
        policy=policy,
        options=ReportOptions(),
        settings=settings,
    )


def run_generate_visual_artifacts(
    *,
    run_ids: list[str] | None = None,
    workdir: str | None = None,
    settings: Settings,
) -> ReportToolResult:
    """Collect / convert PRESTO plots into published PNG visuals + thumbnails."""
    policy = ArtifactPolicy(
        **{**_ALL_OFF, "export_visual_png": True, "export_thumbnails": True}
    )
    return generate_bundle(
        tool_name="generate_visual_artifacts",
        run_ids=run_ids,
        workdir=workdir,
        input_file=None,
        policy=policy,
        options=ReportOptions(),
        settings=settings,
    )


def run_generate_candidate_waterfalls(
    *,
    run_ids: list[str] | None = None,
    workdir: str | None = None,
    input_file: str,
    settings: Settings,
    backend: BackendProtocol,
    candidate_selection: str = "top_n",
    top_n: int = 10,
    candidate_id: str | None = None,
    min_snr: float | None = None,
    min_dm: float | None = None,
    max_dm: float | None = None,
    time_window_sec: float | None = None,
    colour_map: str | None = None,
    color_map: str | None = None,  # deprecated alias for colour_map
    export_png: bool = True,
    export_pdf: bool = False,
) -> ReportToolResult:
    """Render per-candidate waterfall **quicklook** (PNG, optional PDF).

    .. warning::
       This is an MCP-side quicklook for bulk triage. Candidate selection
       (top-N / DM / SNR / window) is MCP logic, not PRESTO single-pulse
       diagnostic semantics. For a canonical single-pulse diagnostic, use
       ``make_spd`` → ``plot_spd`` instead. The ``.spd`` file is PRESTO's
       authoritative single-pulse artifact.

    ``colour_map`` is canonical (matches PRESTO upstream ``--colour-map``).
    ``color_map`` is accepted as a deprecated alias.
    """
    cmap = colour_map if colour_map is not None else color_map
    if cmap is None:
        cmap = "inferno"
    policy = ArtifactPolicy(
        **{
            **_ALL_OFF,
            "export_summary_json": True,
            "export_candidates_csv": True,
            "export_waterfall_png": export_png,
            "export_waterfall_pdf": export_pdf,
            "export_report_html": True,
        },
        default_waterfall_cmap=cmap,
    )
    options = ReportOptions(
        waterfall_cmap=cmap,
        waterfall_window_sec=time_window_sec or 1.0,
    )
    return generate_bundle(
        tool_name="generate_candidate_waterfalls",
        run_ids=run_ids,
        workdir=workdir,
        input_file=input_file,
        policy=policy,
        options=options,
        settings=settings,
        backend=backend,
        waterfall_selection=candidate_selection,
        waterfall_top_n=top_n,
        waterfall_candidate_id=candidate_id,
        waterfall_min_snr=min_snr,
        waterfall_min_dm=min_dm,
        waterfall_max_dm=max_dm,
        waterfall_window_sec=time_window_sec,
    )


def run_generate_report_html(
    *,
    run_ids: list[str] | None = None,
    workdir: str | None = None,
    input_file: str | None = None,
    settings: Settings,
    self_contained: bool = False,
    title: str | None = None,
) -> ReportToolResult:
    """Generate an offline ``report.html`` (with summary, candidates, visuals)."""
    policy = ArtifactPolicy(
        **{
            **_ALL_OFF,
            "export_summary_json": True,
            "export_candidates_csv": True,
            "export_visual_png": True,
            "export_thumbnails": True,
            "export_report_html": True,
        }
    )
    return generate_bundle(
        tool_name="generate_report_html",
        run_ids=run_ids,
        workdir=workdir,
        input_file=input_file,
        policy=policy,
        options=ReportOptions(self_contained_html=self_contained, title=title),
        settings=settings,
    )


def run_generate_report_markdown(
    *,
    run_ids: list[str] | None = None,
    workdir: str | None = None,
    input_file: str | None = None,
    settings: Settings,
    title: str | None = None,
) -> ReportToolResult:
    """Generate a lightweight ``report.md`` text report."""
    policy = ArtifactPolicy(
        **{
            **_ALL_OFF,
            "export_summary_json": True,
            "export_candidates_csv": True,
            "export_report_markdown": True,
        }
    )
    return generate_bundle(
        tool_name="generate_report_markdown",
        run_ids=run_ids,
        workdir=workdir,
        input_file=input_file,
        policy=policy,
        options=ReportOptions(title=title),
        settings=settings,
    )


def run_generate_modern_report_bundle(
    *,
    run_ids: list[str] | None = None,
    workdir: str | None = None,
    input_file: str | None = None,
    settings: Settings,
    backend: BackendProtocol | None = None,
    wants_metadata_only: bool = False,
    wants_candidates: bool = False,
    wants_visuals: bool = False,
    wants_waterfalls: bool = False,
    wants_waterfall_pdf: bool = False,
    wants_report: bool = False,
    wants_no_extra_files: bool = False,
    wants_original_presto_outputs: bool = False,
    title: str | None = None,
    waterfall_cmap: str = "inferno",
    self_contained_html: bool = False,
    waterfall_selection: str = "top_n",
    waterfall_top_n: int = 10,
) -> ReportToolResult:
    """Generate a full modern report bundle, routed from intention flags.

    With no intention flag set, defaults to the full report bundle.
    """
    # Users asking for the "full report" expect waterfalls in HTML.
    auto_waterfalls_for_report = bool(
        wants_report and input_file is not None and backend is not None
    )
    flags = IntentionFlags(
        wants_metadata_only=wants_metadata_only,
        wants_candidates=wants_candidates,
        wants_visuals=wants_visuals,
        wants_waterfalls=(wants_waterfalls or auto_waterfalls_for_report),
        wants_waterfall_pdf=wants_waterfall_pdf,
        wants_report=wants_report,
        wants_no_extra_files=wants_no_extra_files,
        wants_original_presto_outputs=wants_original_presto_outputs,
    )
    # Default to the full bundle only when the caller set no intention flag at all.
    if not any(flags.model_dump().values()):
        flags.wants_report = True
    policy = route_intention(flags)
    policy.default_waterfall_cmap = waterfall_cmap
    selection_effective = waterfall_selection
    top_n_effective = waterfall_top_n

    # Full report mode should be global by default: all parsed events and all
    # renderable waterfalls (including low-DM/RFI-like events), unless caller
    # explicitly overrides selection.
    if flags.wants_report:
        policy.max_candidates_in_html = 1_000_000
        if (
            selection_effective == "top_n"
            and top_n_effective == 10
            and input_file is not None
            and backend is not None
        ):
            selection_effective = "all"
        if selection_effective == "all":
            policy.max_candidates_for_waterfalls = 1_000_000

    return generate_bundle(
        tool_name="generate_modern_report_bundle",
        run_ids=run_ids,
        workdir=workdir,
        input_file=input_file,
        policy=policy,
        options=ReportOptions(
            title=title,
            waterfall_cmap=waterfall_cmap,
            self_contained_html=self_contained_html,
        ),
        settings=settings,
        backend=backend,
        waterfall_selection=selection_effective,
        waterfall_top_n=top_n_effective,
    )


__all__ = [
    "run_export_candidates_csv",
    "run_generate_candidate_waterfalls",
    "run_generate_modern_report_bundle",
    "run_generate_report_html",
    "run_generate_report_markdown",
    "run_generate_summary_json",
    "run_generate_visual_artifacts",
]
