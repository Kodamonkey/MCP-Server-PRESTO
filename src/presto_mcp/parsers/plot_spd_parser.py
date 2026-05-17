"""Parse PRESTO ``plot_spd.py`` output into a typed :class:`PlotSpdResult`.

plot_spd.py reads a ``.spd`` and writes a PNG (or PS) diagnostic plot. The
output filename is controlled via ``-o``.
"""

from __future__ import annotations

import logging
from pathlib import Path

from ..errors import ParserError
from ..models import PlotSpdResult

log = logging.getLogger("presto_mcp.parsers.plot_spd")

_BOM = "﻿"


def parse(
    stdout: str,
    run_dir: Path | None = None,
    *,
    input_spd: str = "",
) -> PlotSpdResult:
    if not isinstance(stdout, str):
        raise ParserError(f"stdout must be str, got {type(stdout).__name__}")
    if stdout.startswith(_BOM):
        stdout = stdout[1:]

    png_file: str | None = None
    if run_dir is not None:
        artifacts_dir = run_dir / "artifacts"
        if artifacts_dir.is_dir():
            for ext in ("*.png", "*.ps", "*.pdf"):
                hits = sorted(artifacts_dir.glob(ext))
                if hits:
                    png_file = hits[0].name
                    break

    return PlotSpdResult(input_spd=input_spd, png_file=png_file)
