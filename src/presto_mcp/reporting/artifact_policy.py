"""Intention routing: prompt-derived flags -> :class:`ArtifactPolicy`.

The LLM decides *what the user wants* and sets the boolean flags in
:class:`IntentionFlags`. This module turns those flags into a concrete
artifact policy using the routing rules from the spec. No NLP happens here.
"""

from __future__ import annotations

from .schemas import ArtifactPolicy, IntentionFlags


def route_intention(
    flags: IntentionFlags,
    *,
    base: ArtifactPolicy | None = None,
) -> ArtifactPolicy:
    """Return the :class:`ArtifactPolicy` implied by ``flags``.

    Routing rules (additive unless noted):

    * ``wants_no_extra_files`` — reset everything off; only flags set *after*
      this turn artifacts back on.
    * ``wants_metadata_only`` — summary.json only, everything else off.
    * ``wants_candidates`` — summary.json + candidates.csv.
    * ``wants_visuals`` — visual PNGs + thumbnails + HTML report.
    * ``wants_waterfalls`` — waterfall PNGs + visual PNGs + HTML report.
    * ``wants_waterfall_pdf`` — waterfall PDFs.
    * ``wants_report`` — the full bundle (summary, csv, visuals, thumbnails,
      HTML, Markdown).
    * ``wants_original_presto_outputs`` — also publish raw PRESTO files.
    """
    p = (base or ArtifactPolicy()).model_copy(deep=True)

    if flags.wants_no_extra_files:
        p.export_summary_json = False
        p.export_candidates_csv = False
        p.export_visual_png = False
        p.export_thumbnails = False
        p.export_waterfall_png = False
        p.export_waterfall_pdf = False
        p.export_report_html = False
        p.export_report_markdown = False

    if flags.wants_metadata_only:
        p.export_summary_json = True
        p.export_candidates_csv = False
        p.export_visual_png = False
        p.export_thumbnails = False
        p.export_waterfall_png = False
        p.export_waterfall_pdf = False
        p.export_report_html = False
        p.export_report_markdown = False

    if flags.wants_candidates:
        p.export_summary_json = True
        p.export_candidates_csv = True

    if flags.wants_visuals:
        p.export_visual_png = True
        p.export_thumbnails = True
        p.export_report_html = True

    if flags.wants_waterfalls:
        p.export_waterfall_png = True
        p.export_visual_png = True
        p.export_report_html = True

    if flags.wants_waterfall_pdf:
        p.export_waterfall_pdf = True

    if flags.wants_report:
        p.export_summary_json = True
        p.export_candidates_csv = True
        p.export_visual_png = True
        p.export_thumbnails = True
        p.export_report_html = True
        p.export_report_markdown = True

    if flags.wants_original_presto_outputs:
        p.export_original_presto_outputs = True

    return p


__all__ = ["route_intention"]
