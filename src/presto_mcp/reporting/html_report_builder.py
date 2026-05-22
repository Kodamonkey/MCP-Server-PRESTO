"""Render a modern, offline ``report.html`` for astronomer-facing inspection.

Plain HTML + embedded CSS + minimal vanilla JavaScript (a sortable candidate
table). No external CDNs, no build step — the file works fully offline with
relative asset paths. An optional self-contained mode base64-embeds images.

Scientific language is deliberately conservative: the report never claims a
discovery, only describes plausible candidates, likely RFI/noise, and cases
that need human inspection.
"""

from __future__ import annotations

import base64
import html
import json
import logging
from pathlib import Path

from .artifact_manager import ArtifactManager
from .schemas import (
    Candidate,
    CandidateType,
    ReportArtifactKind,
    ReportManifest,
    ReportOptions,
    RunReportSummary,
)

log = logging.getLogger("presto_mcp.reporting.html_report_builder")

_DETAIL_CARD_LIMIT = 24


def build_html(
    *,
    summary: RunReportSummary,
    candidates: list[Candidate],
    am: ArtifactManager,
    options: ReportOptions,
    manifest: ReportManifest,
) -> str:
    """Return the full ``report.html`` document as a string."""
    title = options.title or f"PRESTO Report — {summary.run_id}"
    max_rows = manifest.artifact_policy.max_candidates_in_html
    shown = candidates[:max_rows]

    chunks = [
        "<!DOCTYPE html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{html.escape(title)}</title>",
        f"<style>{_CSS}</style>",
        "</head>",
        "<body>",
        '<main class="wrap">',
        _header(summary, title, candidates, manifest),
        _observation(summary),
        _workflow(summary, manifest),
        _candidate_overview(summary, candidates),
        _candidate_table(shown, candidates, max_rows),
        _gallery(am, options),
        _candidate_cards(shown, am, options),
        _rfi_section(summary),
        _interpretation(summary, candidates),
        _reproducibility(summary, manifest, options),
        "</main>",
        f"<script>{_JS}</script>",
        "</body>",
        "</html>",
    ]
    return "\n".join(chunks)


# -- sections ------------------------------------------------------------------


def _header(
    summary: RunReportSummary,
    title: str,
    candidates: list[Candidate],
    manifest: ReportManifest,
) -> str:
    badges = [
        _badge(f"{len(candidates)} candidates", bool(candidates)),
        _badge("RFI diagnostics", summary.rfi_summary.available),
        _badge("visuals", bool(manifest.visuals)),
        _badge("waterfalls", bool(manifest.waterfall_png or manifest.waterfall_pdf)),
    ]
    status_class = {"success": "ok", "partial": "warn", "failed": "err"}.get(
        summary.status, "warn"
    )
    return (
        '<header class="hdr">'
        f"<h1>{html.escape(title)}</h1>"
        '<div class="meta">'
        f"<span><b>Run ID</b> {html.escape(summary.run_id)}</span>"
        f"<span><b>Input</b> {html.escape(summary.input_file or '—')}</span>"
        f"<span><b>Generated</b> {html.escape(summary.generated_at.isoformat())}</span>"
        f'<span class="status {status_class}"><b>Status</b> {html.escape(summary.status)}</span>'
        "</div>"
        f'<div class="badges">{"".join(badges)}</div>'
        "</header>"
    )


def _observation(summary: RunReportSummary) -> str:
    o = summary.observation
    freq = "—"
    if o.central_freq_mhz is not None:
        freq = f"{o.central_freq_mhz:.3f} MHz centre"
    rows = [
        ("File type", o.file_type),
        ("Telescope / instrument", _join(o.telescope, o.instrument)),
        ("Source name", o.source_name),
        ("Start MJD", _fmt(o.mjd_start, 6)),
        ("Duration", _unit(o.duration_sec, "s")),
        ("Centre frequency", freq),
        ("Bandwidth", _unit(o.bandwidth_mhz, "MHz")),
        ("Channels", o.nchans),
        ("Sampling time", _unit(o.tsamp_us, "µs")),
    ]
    return _section("B. Observation Summary", _kv_table(rows))


def _workflow(summary: RunReportSummary, manifest: ReportManifest) -> str:
    tools = ", ".join(html.escape(t) for t in summary.tools_executed) or "—"
    failed = ", ".join(html.escape(t) for t in summary.failed_tools) or "—"
    rows = [
        ("Tools executed", tools),
        ("Failed tools", failed),
        ("Total runtime", _unit(summary.total_runtime_sec, "s")),
        ("DM trials", summary.dm_trials),
    ]
    body = _kv_table(rows)
    if summary.warnings:
        body += _list_block("Warnings", summary.warnings)
    return _section("C. PRESTO Workflow Summary", body)


def _candidate_overview(summary: RunReportSummary, candidates: list[Candidate]) -> str:
    c = summary.candidate_counts
    rows = [
        ("Total", c.total),
        ("Single pulse", c.single_pulse),
        ("Periodic", c.periodic),
        ("Acceleration", c.acceleration),
        ("Folded", c.folded),
        ("RRAT group", c.rrat_group),
        ("Unknown", c.unknown),
    ]
    body = _kv_table(rows)
    body += '<p><a href="candidates.csv">Download candidates.csv</a></p>'
    return _section("D. Candidate Overview", body)


def _candidate_table(
    shown: list[Candidate], candidates: list[Candidate], max_rows: int
) -> str:
    if not candidates:
        return _section("E. Candidate Table", "<p>No candidates were detected.</p>")
    head = (
        "<thead><tr>"
        + "".join(
            f'<th onclick="sortTable(this)">{h}</th>'
            for h in (
                "ID",
                "Type",
                "DM",
                "SNR/σ",
                "Time (s)",
                "Period (s)",
                "Accel/z",
                "Rank",
                "RFI hint",
                "Links",
            )
        )
        + "</tr></thead>"
    )
    body_rows = []
    for c in shown:
        links = []
        if c.paths.waterfall_png_path:
            links.append(f'<a href="{html.escape(c.paths.waterfall_png_path)}">wf.png</a>')
        if c.paths.waterfall_pdf_path:
            links.append(f'<a href="{html.escape(c.paths.waterfall_pdf_path)}">wf.pdf</a>')
        if c.paths.candidate_json_path:
            links.append(f'<a href="{html.escape(c.paths.candidate_json_path)}">json</a>')
        body_rows.append(
            "<tr>"
            f"<td>{html.escape(c.candidate_id)}</td>"
            f"<td>{html.escape(c.candidate_type.value)}</td>"
            f"<td>{_fmt(c.dm, 3)}</td>"
            f"<td>{_fmt(c.snr_or_sigma, 2)}</td>"
            f"<td>{_fmt(c.time_sec, 4)}</td>"
            f"<td>{_fmt(c.period_sec, 9)}</td>"
            f"<td>{_fmt(c.acceleration_or_z, 3)}</td>"
            f"<td>{c.rank if c.rank is not None else '—'}</td>"
            f"<td>{'RFI-like' if c.is_rfi_like else '—'}</td>"
            f"<td>{' '.join(links) or '—'}</td>"
            "</tr>"
        )
    note = ""
    if len(candidates) > max_rows:
        note = f"<p class='muted'>Showing {max_rows} of {len(candidates)} candidates.</p>"
    table = f'<table class="cand">{head}<tbody>{"".join(body_rows)}</tbody></table>'
    return _section("E. Candidate Table", table + note)


def _gallery(am: ArtifactManager, options: ReportOptions) -> str:
    thumbs = am.artifacts_of(ReportArtifactKind.THUMBNAIL)
    visuals = am.artifacts_of(ReportArtifactKind.VISUAL_PNG)
    waterfalls = am.artifacts_of(ReportArtifactKind.WATERFALL_PNG)
    if not (visuals or waterfalls):
        return _section("F. Visual Diagnostics Gallery", "<p>No visual artifacts.</p>")
    by_name = {Path(t.path).name: t.path for t in thumbs}
    tiles = []
    for v in visuals + waterfalls:
        name = Path(v.path).name
        thumb = by_name.get(name, v.path)
        tiles.append(
            f'<figure><a href="{html.escape(v.path)}">'
            f'<img loading="lazy" src="{_img_src(am, thumb, options)}" alt="{html.escape(name)}">'
            f"</a><figcaption>{html.escape(name)}</figcaption></figure>"
        )
    return _section("F. Visual Diagnostics Gallery", f'<div class="grid">{"".join(tiles)}</div>')


def _candidate_cards(
    shown: list[Candidate], am: ArtifactManager, options: ReportOptions
) -> str:
    relevant = [c for c in shown if c.paths.waterfall_png_path][:_DETAIL_CARD_LIMIT]
    if not relevant:
        relevant = shown[:_DETAIL_CARD_LIMIT]
    if not relevant:
        return _section("G. Candidate Detail Cards", "<p>No candidates to detail.</p>")
    cards = []
    for c in relevant:
        img = ""
        if c.paths.waterfall_png_path:
            img = (
                f'<img loading="lazy" src="{_img_src(am, c.paths.waterfall_png_path, options)}" '
                f'alt="waterfall {html.escape(c.candidate_id)}">'
            )
        meta_json = json.dumps(
            c.model_dump(mode="json"), indent=2, ensure_ascii=True
        )
        rows = _kv_table(
            [
                ("Type", c.candidate_type.value),
                ("DM", _fmt(c.dm, 3)),
                ("SNR/σ", _fmt(c.snr_or_sigma, 2)),
                ("Time (s)", _fmt(c.time_sec, 4)),
                ("Period (s)", _fmt(c.period_sec, 9)),
                ("Accel/z", _fmt(c.acceleration_or_z, 3)),
                ("Rank", c.rank),
                ("Classification hint", c.classification_hint),
            ]
        )
        cards.append(
            '<article class="card">'
            f"<h3>{html.escape(c.candidate_id)}</h3>"
            f"{rows}{img}"
            "<details><summary>Raw metadata</summary>"
            f"<pre>{html.escape(meta_json)}</pre></details>"
            "</article>"
        )
    return _section("G. Candidate Detail Cards", f'<div class="cards">{"".join(cards)}</div>')


def _rfi_section(summary: RunReportSummary) -> str:
    r = summary.rfi_summary
    if not r.available:
        return _section("H. RFI and Data Quality", "<p>No RFI diagnostics available.</p>")
    rows = [
        ("Mask / RFI files", ", ".join(r.mask_files) or "—"),
        ("Bad channels", len(r.bad_channels) or "—"),
        ("Bad intervals", len(r.bad_intervals) or "—"),
        ("Masked fraction", _unit(r.pct_masked, "%")),
    ]
    body = _kv_table(rows)
    if r.notes:
        body += _list_block("Notes", r.notes)
    return _section("H. RFI and Data Quality", body)


def _interpretation(summary: RunReportSummary, candidates: list[Candidate]) -> str:
    plausible = [
        c
        for c in candidates
        if not c.is_rfi_like
        and (
            c.candidate_type != CandidateType.SINGLE_PULSE
            or (c.snr_or_sigma is not None and c.snr_or_sigma >= 7.0)
        )
    ]
    rfi_like = [c for c in candidates if c.is_rfi_like]
    body = (
        "<p>This is an automated, conservative summary. It does <b>not</b> assert a "
        "discovery. All candidates require human inspection before any scientific claim.</p>"
        "<ul>"
        f"<li><b>Plausible candidates:</b> {len(plausible)} — significant detections "
        "worth human inspection (no confirmation implied).</li>"
        f"<li><b>Likely RFI / noise:</b> {len(rfi_like)} — near-zero-DM or "
        "low-significance events consistent with interference.</li>"
        f"<li><b>Total parsed:</b> {len(candidates)}.</li>"
        "</ul>"
    )
    if not candidates:
        body += "<p>No candidates were parsed — insufficient evidence of any transient.</p>"
    return _section("I. Interpretation Notes", body)


def _reproducibility(
    summary: RunReportSummary, manifest: ReportManifest, options: ReportOptions
) -> str:
    links = ['<a href="manifest.json">manifest.json</a>']
    if manifest.summary_json:
        links.append(f'<a href="{html.escape(manifest.summary_json)}">summary.json</a>')
    if manifest.candidates_csv:
        links.append(f'<a href="{html.escape(manifest.candidates_csv)}">candidates.csv</a>')
    if options.include_observability_links:
        if manifest.status_md:
            links.append(f'<a href="{html.escape(manifest.status_md)}">status.md</a>')
        if manifest.timeline_json:
            links.append(f'<a href="{html.escape(manifest.timeline_json)}">timeline.json</a>')
    body = (
        "<p>Tools executed: "
        + (", ".join(html.escape(t) for t in summary.tools_executed) or "—")
        + "</p><p>Artifacts: "
        + " · ".join(links)
        + "</p>"
    )
    if summary.errors:
        body += _list_block("Errors", summary.errors)
    return _section("J. Reproducibility", body)


# -- helpers -------------------------------------------------------------------


def _section(title: str, body: str) -> str:
    return f'<section><h2>{html.escape(title)}</h2>{body}</section>'


def _badge(text: str, on: bool) -> str:
    cls = "badge on" if on else "badge"
    return f'<span class="{cls}">{html.escape(text)}</span>'


def _kv_table(rows: list[tuple[str, object]]) -> str:
    cells = "".join(
        f"<tr><th>{html.escape(k)}</th><td>{_cell(v)}</td></tr>" for k, v in rows
    )
    return f'<table class="kv">{cells}</table>'


def _list_block(title: str, items: list[str]) -> str:
    lis = "".join(f"<li>{html.escape(str(i))}</li>" for i in items)
    return f"<h4>{html.escape(title)}</h4><ul>{lis}</ul>"


def _cell(value: object) -> str:
    if value is None or value == "":
        return "—"
    return html.escape(str(value))


def _fmt(value: float | None, digits: int) -> str:
    if value is None:
        return "—"
    return f"{value:.{digits}f}"


def _unit(value: float | None, unit: str) -> str:
    if value is None:
        return "—"
    return f"{value:g} {unit}"


def _join(*parts: str | None) -> str | None:
    kept = [p for p in parts if p]
    return " / ".join(kept) if kept else None


def _img_src(am: ArtifactManager, rel_path: str, options: ReportOptions) -> str:
    """Return an ``<img>`` src — relative path, or a base64 data URI."""
    if not options.self_contained_html:
        return html.escape(rel_path)
    abs_path = (am.run_dir / rel_path).resolve()
    try:
        data = abs_path.read_bytes()
    except OSError:
        return html.escape(rel_path)
    b64 = base64.b64encode(data).decode("ascii")
    return f"data:image/png;base64,{b64}"


_CSS = """
:root{--bg:#f6f7f9;--fg:#1c2128;--mut:#5b6470;--line:#dfe3e8;--acc:#1f6feb;
--ok:#1a7f37;--warn:#9a6700;--err:#cf222e;--card:#fff}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
font:15px/1.55 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif}
.wrap{max-width:1100px;margin:0 auto;padding:24px}
.hdr{background:var(--card);border:1px solid var(--line);border-radius:12px;
padding:20px 24px;margin-bottom:20px}
h1{margin:0 0 10px;font-size:22px}
h2{font-size:17px;margin:0 0 12px;border-bottom:2px solid var(--acc);
padding-bottom:6px;display:inline-block}
h3{margin:0 0 8px;font-size:15px}h4{margin:14px 0 4px;font-size:13px;color:var(--mut)}
.meta{display:flex;flex-wrap:wrap;gap:8px 20px;color:var(--mut);font-size:13px}
.meta b{color:var(--fg)}
.status.ok b{color:var(--ok)}.status.warn b{color:var(--warn)}.status.err b{color:var(--err)}
.badges{margin-top:12px;display:flex;flex-wrap:wrap;gap:8px}
.badge{background:#eceff3;color:var(--mut);border-radius:20px;padding:3px 12px;
font-size:12px;border:1px solid var(--line)}
.badge.on{background:#ddeaff;color:var(--acc);border-color:#bcd6ff}
section{background:var(--card);border:1px solid var(--line);border-radius:12px;
padding:18px 24px;margin-bottom:18px}
table{border-collapse:collapse;width:100%;font-size:13px}
table.kv th{text-align:left;color:var(--mut);font-weight:600;width:240px;
padding:4px 10px 4px 0;vertical-align:top}
table.kv td{padding:4px 0}
table.cand th,table.cand td{border:1px solid var(--line);padding:6px 9px;text-align:left}
table.cand th{background:#f0f2f5;cursor:pointer;user-select:none;position:sticky;top:0}
table.cand tbody tr:nth-child(even){background:#fafbfc}
a{color:var(--acc)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:14px}
figure{margin:0;background:#fafbfc;border:1px solid var(--line);border-radius:8px;padding:8px}
figure img{width:100%;height:auto;border-radius:4px;display:block}
figcaption{font-size:11px;color:var(--mut);margin-top:6px;word-break:break-all}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:16px}
.card{border:1px solid var(--line);border-radius:10px;padding:14px;background:#fafbfc}
.card img{width:100%;height:auto;border-radius:6px;margin-top:8px}
pre{background:#0d1117;color:#c9d1d9;padding:12px;border-radius:8px;overflow:auto;
font-size:12px}
details summary{cursor:pointer;color:var(--acc);font-size:13px;margin-top:8px}
.muted{color:var(--mut);font-size:12px}
ul{margin:4px 0;padding-left:20px}
"""

_JS = """
function sortTable(th){
 var t=th.closest('table'),tb=t.tBodies[0],
 i=Array.prototype.indexOf.call(th.parentNode.children,th),
 asc=th.dataset.asc!=='1';th.dataset.asc=asc?'1':'0';
 var rows=Array.prototype.slice.call(tb.rows);
 rows.sort(function(a,b){
  var x=a.cells[i].textContent.trim(),y=b.cells[i].textContent.trim();
  var nx=parseFloat(x),ny=parseFloat(y);
  if(!isNaN(nx)&&!isNaN(ny))return asc?nx-ny:ny-nx;
  return asc?x.localeCompare(y):y.localeCompare(x);
 });
 rows.forEach(function(r){tb.appendChild(r);});
}
"""


__all__ = ["build_html"]
