"""Render a lightweight ``report.md`` text report.

A compact, plain-text counterpart to ``report.html`` — observation summary,
workflow summary, candidate table, artifact links and conservative
interpretation notes. Uses only relative links so it stays portable.
"""

from __future__ import annotations

import logging

from .schemas import Candidate, CandidateType, ReportManifest, ReportOptions, RunReportSummary

log = logging.getLogger("presto_mcp.reporting.markdown_report_builder")

_TOP_ROWS = 25


def build_markdown(
    *,
    summary: RunReportSummary,
    candidates: list[Candidate],
    options: ReportOptions,
    manifest: ReportManifest,
) -> str:
    """Return the full ``report.md`` document as a string."""
    o = summary.observation
    c = summary.candidate_counts
    lines: list[str] = []

    lines.append(f"# {options.title or 'PRESTO Report'} — {summary.run_id}")
    lines.append("")
    lines.append(f"- **Input:** {summary.input_file or '—'}")
    lines.append(f"- **Generated:** {summary.generated_at.isoformat()}")
    lines.append(f"- **Status:** {summary.status}")
    lines.append("")

    lines.append("## Observation Summary")
    lines.append("")
    for label, value in (
        ("File type", o.file_type),
        ("Telescope", o.telescope),
        ("Instrument", o.instrument),
        ("Source name", o.source_name),
        ("Start MJD", o.mjd_start),
        ("Duration (s)", o.duration_sec),
        ("Centre freq (MHz)", o.central_freq_mhz),
        ("Bandwidth (MHz)", o.bandwidth_mhz),
        ("Channels", o.nchans),
        ("Sampling time (µs)", o.tsamp_us),
    ):
        lines.append(f"- **{label}:** {value if value is not None else '—'}")
    lines.append("")

    lines.append("## PRESTO Workflow Summary")
    lines.append("")
    lines.append(f"- **Tools executed:** {', '.join(summary.tools_executed) or '—'}")
    lines.append(f"- **Failed tools:** {', '.join(summary.failed_tools) or '—'}")
    lines.append(f"- **Total runtime (s):** {summary.total_runtime_sec if summary.total_runtime_sec is not None else '—'}")
    lines.append("")

    lines.append("## Candidate Summary")
    lines.append("")
    lines.append(f"- **Total:** {c.total}")
    lines.append(f"- **Single pulse:** {c.single_pulse}")
    lines.append(f"- **Periodic:** {c.periodic}")
    lines.append(f"- **Acceleration:** {c.acceleration}")
    lines.append(f"- **Folded:** {c.folded}")
    lines.append(f"- **RRAT group:** {c.rrat_group}")
    lines.append(f"- **Unknown:** {c.unknown}")
    lines.append("")

    lines.append("## Top Candidates")
    lines.append("")
    if candidates:
        lines.append("| Rank | ID | Type | DM | SNR/σ | Time (s) | Period (s) |")
        lines.append("|---|---|---|---|---|---|---|")
        ranked = sorted(candidates, key=lambda x: (x.rank is None, x.rank or 1_000_000))
        for cand in ranked[:_TOP_ROWS]:
            lines.append(
                f"| {cand.rank if cand.rank is not None else '—'} "
                f"| {cand.candidate_id} | {cand.candidate_type.value} "
                f"| {_num(cand.dm)} | {_num(cand.snr_or_sigma)} "
                f"| {_num(cand.time_sec)} | {_num(cand.period_sec)} |"
            )
        if len(candidates) > _TOP_ROWS:
            lines.append("")
            lines.append(f"_Showing {_TOP_ROWS} of {len(candidates)} — see candidates.csv._")
    else:
        lines.append("_No candidates were detected._")
    lines.append("")

    lines.append("## Artifacts")
    lines.append("")
    if manifest.candidates_csv:
        lines.append(f"- [candidates.csv]({manifest.candidates_csv})")
    if manifest.summary_json:
        lines.append(f"- [summary.json]({manifest.summary_json})")
    if manifest.report_html:
        lines.append(f"- [report.html]({manifest.report_html})")
    lines.append("- [manifest.json](manifest.json)")
    for art in manifest.visuals[:30]:
        lines.append(f"- visual: [{art.path}]({art.path})")
    for art in manifest.waterfall_png[:30]:
        lines.append(f"- waterfall PNG: [{art.path}]({art.path})")
    for art in manifest.waterfall_pdf[:30]:
        lines.append(f"- waterfall PDF: [{art.path}]({art.path})")
    if options.include_observability_links and manifest.status_md:
        lines.append(f"- [status.md]({manifest.status_md})")
    lines.append("")

    if summary.warnings:
        lines.append("## Warnings")
        lines.append("")
        lines.extend(f"- {w}" for w in summary.warnings)
        lines.append("")
    if summary.errors:
        lines.append("## Errors")
        lines.append("")
        lines.extend(f"- {e}" for e in summary.errors)
        lines.append("")

    lines.append("## Interpretation Notes")
    lines.append("")
    plausible = sum(
        1
        for x in candidates
        if not x.is_rfi_like
        and (
            x.candidate_type != CandidateType.SINGLE_PULSE
            or (x.snr_or_sigma is not None and x.snr_or_sigma >= 7.0)
        )
    )
    rfi_like = sum(1 for x in candidates if x.is_rfi_like)
    lines.append(
        "This is an automated, conservative summary. It does **not** assert a "
        "discovery — every candidate requires human inspection."
    )
    lines.append("")
    lines.append(f"- **Plausible candidates:** {plausible} (require human inspection)")
    lines.append(f"- **Likely RFI / noise:** {rfi_like}")
    lines.append(f"- **Total parsed:** {len(candidates)}")
    lines.append("")

    return "\n".join(lines) + "\n"


def _num(value: float | None) -> str:
    return "—" if value is None else f"{value:g}"


__all__ = ["build_markdown"]
