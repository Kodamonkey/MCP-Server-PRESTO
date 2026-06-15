"""Human-readable index of the outputs/ report bundles.

Regenerated after each bundle build:

  * ``outputs/INDEX.md``   — newest-first table of report bundles
  * ``outputs/index.json`` — machine view

Also maintains ``outputs/latest_report.html`` / ``outputs/latest_summary.json``
pointers (plain copies — Windows-safe, no symlinks). Best-effort: never raises
into a bundle build.
"""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path

log = logging.getLogger("presto_mcp.reporting.output_index")

INDEX_MD = "INDEX.md"
INDEX_JSON = "index.json"
LATEST_REPORT = "latest_report.html"
LATEST_SUMMARY = "latest_summary.json"

# Top-level files this module owns — never treat them as bundle dirs.
_RESERVED = {INDEX_MD, INDEX_JSON, LATEST_REPORT, LATEST_SUMMARY}


def _bundle_rows(outputs_root: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for child in outputs_root.iterdir():
        if not child.is_dir() or child.name in _RESERVED:
            continue
        manifest = child / "manifest.json"
        if not manifest.is_file():
            continue
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        candidates = _candidate_count(child)
        rows.append(
            {
                "bundle": child.name,
                "run_id": data.get("run_id"),
                "status": data.get("status"),
                "generated_at": data.get("generated_at"),
                "report_html": data.get("report_html"),
                "candidate_count": candidates,
                "mtime": manifest.stat().st_mtime,
            }
        )
    rows.sort(key=lambda r: r["mtime"], reverse=True)  # newest first
    return rows


def _candidate_count(bundle_dir: Path) -> int | None:
    summary = bundle_dir / "summary.json"
    if not summary.is_file():
        return None
    try:
        data = json.loads(summary.read_text(encoding="utf-8"))
        counts = data.get("candidate_counts")
        if isinstance(counts, dict) and isinstance(counts.get("total"), int):
            return counts["total"]
    except (OSError, json.JSONDecodeError):
        return None
    return None


def _cell(value: object) -> str:
    if value is None or value == "":
        return "—"
    return str(value).replace("|", "\\|")


def _render_md(rows: list[dict[str, object]]) -> str:
    lines = [
        "# Report bundles index",
        "",
        f"_{len(rows)} bundle(s); newest first._",
        "",
        "| Bundle | Status | Candidates | Report |",
        "|---|---|---|---|",
    ]
    for r in rows:
        report = r.get("report_html")
        link = f"[{r['bundle']}/report.html]({_cell(r['bundle'])}/report.html)" if report else "—"
        lines.append(
            "| "
            + " | ".join(
                [_cell(r["bundle"]), _cell(r["status"]), _cell(r["candidate_count"]), link]
            )
            + " |"
        )
    if not rows:
        lines.append("| _no bundles yet_ |  |  |  |")
    lines.append("")
    return "\n".join(lines)


def _update_latest(outputs_root: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        return
    newest = rows[0]
    bundle_dir = outputs_root / str(newest["bundle"])
    report = bundle_dir / "report.html"
    if report.is_file():
        shutil.copy2(report, outputs_root / LATEST_REPORT)
    summary = bundle_dir / "summary.json"
    if summary.is_file():
        shutil.copy2(summary, outputs_root / LATEST_SUMMARY)


def write_output_index(outputs_root: Path) -> None:
    """Regenerate outputs/INDEX.md + index.json and the latest_* pointers."""
    try:
        outputs_root = Path(outputs_root)
        if not outputs_root.is_dir():
            return
        rows = _bundle_rows(outputs_root)
        (outputs_root / INDEX_MD).write_text(_render_md(rows), encoding="utf-8")
        (outputs_root / INDEX_JSON).write_text(
            json.dumps({"count": len(rows), "bundles": rows}, ensure_ascii=True, indent=2),
            encoding="utf-8",
        )
        _update_latest(outputs_root, rows)
    except Exception:  # noqa: BLE001 - indexing must never break a bundle
        log.warning("output index regeneration failed", exc_info=True)


__all__ = ["write_output_index", "INDEX_MD", "INDEX_JSON", "LATEST_REPORT", "LATEST_SUMMARY"]
