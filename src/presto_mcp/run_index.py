"""Human-readable index of the runs/ tree.

``runs/`` is a flood of cryptic ``<run_id>/`` folders. This module regenerates a
single entry point after every run:

  * ``runs/INDEX.md``   — newest-first table + a "by observation" grouping
  * ``runs/index.json`` — machine view (list of enriched run summaries)

Best-effort: index generation must never break a run. Callers wrap nothing; the
public function swallows its own errors.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path, PurePath

from .manifest import list_run_summaries
from .models import RunSummary
from .run_label import observation_basename

log = logging.getLogger("presto_mcp.run_index")

INDEX_MD = "INDEX.md"
INDEX_JSON = "index.json"

# Cap rows in the rendered table so the file stays readable; index.json is full.
_MD_ROW_LIMIT = 200


def _duration(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    if seconds < 1.0:
        return f"{seconds * 1000:.0f}ms"
    if seconds < 120:
        return f"{seconds:.1f}s"
    return f"{seconds / 60:.1f}m"


def _cell(value: object) -> str:
    if value is None or value == "":
        return "—"
    return str(value).replace("|", "\\|")


def _obs_for(summary: RunSummary) -> str:
    return observation_basename({"input_file": summary.input_file or ""}) or "(no input)"


def _render_md(summaries: list[RunSummary]) -> str:
    lines = [
        "# Runs index",
        "",
        f"_{len(summaries)} run(s); newest first._",
        "",
        "| Time (UTC) | Label | Tool | Input | Status | Duration | run_id |",
        "|---|---|---|---|---|---|---|",
    ]
    for s in summaries[:_MD_ROW_LIMIT]:
        ts = s.started_at.strftime("%Y-%m-%d %H:%M:%S")
        input_name = PurePath(s.input_file.replace("\\", "/")).name if s.input_file else None
        lines.append(
            "| "
            + " | ".join(
                [
                    _cell(ts),
                    _cell(s.label),
                    _cell(s.tool),
                    _cell(input_name),
                    _cell(s.status),
                    _duration(s.duration_s),
                    _cell(s.run_id),
                ]
            )
            + " |"
        )
    if not summaries:
        lines.append("| _no runs yet_ |  |  |  |  |  |  |")

    # By-observation grouping (newest first within each group).
    groups: dict[str, list[RunSummary]] = {}
    for s in summaries:
        groups.setdefault(_obs_for(s), []).append(s)
    lines += ["", "## By observation", ""]
    for obs in sorted(groups):
        lines.append(f"### {obs}")
        for s in groups[obs]:
            lines.append(f"- `{s.run_id}` — {s.tool} ({s.status})")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_run_index(runs_root: Path) -> None:
    """Regenerate ``runs/INDEX.md`` + ``runs/index.json`` from manifests."""
    try:
        runs_root = Path(runs_root)
        if not runs_root.is_dir():
            return
        summaries = list_run_summaries(runs_root)
        (runs_root / INDEX_MD).write_text(_render_md(summaries), encoding="utf-8")
        payload = {
            "count": len(summaries),
            "runs": [s.model_dump(mode="json") for s in summaries],
        }
        (runs_root / INDEX_JSON).write_text(
            json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8"
        )
    except Exception:  # noqa: BLE001 - indexing must never break a run
        log.warning("run index regeneration failed", exc_info=True)


__all__ = ["write_run_index", "INDEX_MD", "INDEX_JSON"]
