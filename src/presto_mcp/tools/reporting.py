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
    color_map: str = "inferno",
    export_png: bool = True,
    export_pdf: bool = False,
) -> ReportToolResult:
    """Render per-candidate waterfall diagnostics (PNG, optional PDF)."""
    policy = ArtifactPolicy(
        **{
            **_ALL_OFF,
            "export_waterfall_png": export_png,
            "export_waterfall_pdf": export_pdf,
        },
        default_waterfall_cmap=color_map,
    )
    options = ReportOptions(
        waterfall_cmap=color_map,
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
    flags = IntentionFlags(
        wants_metadata_only=wants_metadata_only,
        wants_candidates=wants_candidates,
        wants_visuals=wants_visuals,
        wants_waterfalls=wants_waterfalls,
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
        waterfall_selection=waterfall_selection,
        waterfall_top_n=waterfall_top_n,
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
