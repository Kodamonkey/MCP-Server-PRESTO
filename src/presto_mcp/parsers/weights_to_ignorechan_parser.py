"""Parse PRESTO ``weights_to_ignorechan.py`` stdout.

Prints either a comma-separated channel list or a colon-separated range list
(e.g. ``"0:31,64:95,256"``) on stdout. Optionally writes a ``.ignorechan``
artifact. Parsing is best-effort.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from ..errors import ParserError
from ..models import WeightsToIgnorechanResult

log = logging.getLogger("presto_mcp.parsers.weights_to_ignorechan")

_BOM = "﻿"
_TOKEN_LINE = re.compile(r"[0-9]+(?:\s*:\s*[0-9]+)?")


def _expand_tokens(line: str) -> list[int]:
    out: list[int] = []
    for tok in re.split(r"[,\s]+", line.strip()):
        tok = tok.strip()
        if not tok:
            continue
        if ":" in tok:
            try:
                lo, hi = (int(x) for x in tok.split(":", 1))
            except ValueError:
                continue
            if lo <= hi and hi - lo < 100_000:
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
    weights_file: str,
) -> WeightsToIgnorechanResult:
    if not isinstance(stdout, str):
        raise ParserError(f"stdout must be str, got {type(stdout).__name__}")
    if stdout.startswith(_BOM):
        stdout = stdout[1:]

    notes: list[str] = []
    channels: list[int] = []

    # Take the last non-empty line that looks like a channel list.
    for line in reversed([ln for ln in stdout.splitlines() if ln.strip()]):
        if _TOKEN_LINE.search(line):
            channels = _expand_tokens(line)
            if channels:
                break
    if not channels:
        notes.append("no parsable channel list found in stdout")

    ignorechan_file: str | None = None
    if run_dir is not None:
        artifacts_dir = run_dir / "artifacts"
        if artifacts_dir.is_dir():
            for pattern in ("*.ignorechan", "*.txt", "ignorechan*"):
                hits = sorted(artifacts_dir.glob(pattern))
                if hits:
                    ignorechan_file = hits[0].name
                    break

    return WeightsToIgnorechanResult(
        weights_file=weights_file,
        ignorechan_file=ignorechan_file,
        ignore_channels=channels,
        notes=notes,
    )
