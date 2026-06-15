"""Render the live ``status.md`` table for a run."""

from __future__ import annotations

from datetime import UTC, datetime

from .event_types import status_symbol
from .schemas import StatusRow

_HEADER = (
    "| Step | Tool | Input | Status | Duration | Notes |\n"
    "|---|---|---|---|---|---|\n"
)


def _duration(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    if seconds < 1.0:
        return f"{seconds * 1000:.0f}ms"
    return f"{seconds:.1f}s"


def _cell(value: object) -> str:
    if value is None or value == "":
        return "—"
    # Pipes would break the Markdown table.
    return str(value).replace("|", "\\|")


def render_status_md(run_id: str, rows: list[StatusRow]) -> str:
    """Return a Markdown document showing every step of ``run_id``."""
    lines = [
        f"# Run status — {run_id}",
        "",
        f"_Updated {datetime.now(UTC).isoformat()}_",
        "",
        _HEADER.rstrip("\n"),
    ]
    for row in rows:
        symbol = status_symbol(row.status)
        status_cell = f"{symbol} {row.status}".strip()
        lines.append(
            "| "
            + " | ".join(
                [
                    _cell(row.step),
                    _cell(row.tool),
                    _cell(row.input),
                    status_cell,
                    _duration(row.duration_s),
                    _cell(row.notes),
                ]
            )
            + " |"
        )
    if not rows:
        lines.append("| _no steps recorded yet_ |  |  |  |  |  |")
    lines.append("")
    return "\n".join(lines)


__all__ = ["render_status_md"]
