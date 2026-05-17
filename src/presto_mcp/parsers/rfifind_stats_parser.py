"""Parse PRESTO ``rfifind_stats.py`` stdout into :class:`RfifindStatsResult`.

The script summarizes a prior rfifind run's ``.mask`` / ``.stats`` file. Stdout
typically contains a "bad channels" list and a "bad intervals" list. Parsing is
best-effort: missing fields land in ``notes`` rather than raising.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from ..errors import ParserError
from ..models import RfifindStatsResult

log = logging.getLogger("presto_mcp.parsers.rfifind_stats")

_BOM = "﻿"

# Loose patterns: PRESTO scripts have varied over versions. We accept both
# "0-31" and "0:31" range notations and let _expand_ranges handle either.
# The leading "<label> [:=]" is consumed, and we grab the rest of the line.
_BAD_CHANS = re.compile(
    r"bad\s+channels?\s*[:=]\s*([^\r\n]+)", re.IGNORECASE
)
_BAD_INTS = re.compile(
    r"bad\s+intervals?\s*[:=]\s*([^\r\n]+)", re.IGNORECASE
)


def _expand_ranges(raw: str) -> list[int]:
    out: list[int] = []
    for tok in re.split(r"[,\s]+", raw.strip()):
        if not tok:
            continue
        sep: str | None = None
        if "-" in tok:
            sep = "-"
        elif ":" in tok:
            sep = ":"
        if sep is not None:
            try:
                lo, hi = (int(x) for x in tok.split(sep, 1))
            except ValueError:
                continue
            if lo <= hi and hi - lo < 10_000:
                out.extend(range(lo, hi + 1))
        else:
            try:
                out.append(int(tok))
            except ValueError:
                continue
    return out


def parse(
    stdout: str,
    run_dir: Path | None = None,
    *,
    stats_file: str,
    mask_file: str | None = None,
) -> RfifindStatsResult:
    if not isinstance(stdout, str):
        raise ParserError(f"stdout must be str, got {type(stdout).__name__}")
    if stdout.startswith(_BOM):
        stdout = stdout[1:]

    notes: list[str] = []
    bad_channels: list[int] = []
    bad_intervals: list[int] = []

    if (m := _BAD_CHANS.search(stdout)) is not None:
        bad_channels = _expand_ranges(m.group(1))
    else:
        notes.append("no 'bad channels' line found in stdout")

    if (m := _BAD_INTS.search(stdout)) is not None:
        bad_intervals = _expand_ranges(m.group(1))
    else:
        notes.append("no 'bad intervals' line found in stdout")

    summary_file: str | None = None
    if run_dir is not None:
        artifacts_dir = run_dir / "artifacts"
        if artifacts_dir.is_dir():
            for ext in (".txt", ".summary", ".log"):
                hits = sorted(artifacts_dir.glob(f"*{ext}"))
                if hits:
                    summary_file = hits[0].name
                    break

    return RfifindStatsResult(
        stats_file=stats_file,
        mask_file=mask_file,
        summary_file=summary_file,
        bad_channels=bad_channels,
        bad_intervals=bad_intervals,
        notes=notes,
    )
