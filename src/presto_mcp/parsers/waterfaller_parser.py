"""Parse PRESTO ``waterfaller.py`` output into a typed :class:`WaterfallerResult`.

waterfaller.py renders a dynamic-spectrum waterfall around a given start
time / duration / DM. The output file (PNG / PS) is controlled with ``-o``.
"""

from __future__ import annotations

import logging
from pathlib import Path

from ..errors import ParserError
from ..models import WaterfallerResult

log = logging.getLogger("presto_mcp.parsers.waterfaller")

_BOM = "﻿"


def parse(
    stdout: str,
    run_dir: Path | None = None,
    *,
    input_raw: str = "",
    start_s: float = 0.0,
    duration_s: float = 0.0,
    dm: float = 0.0,
    mask_file: str | None = None,
) -> WaterfallerResult:
    if not isinstance(stdout, str):
        raise ParserError(f"stdout must be str, got {type(stdout).__name__}")
    if stdout.startswith(_BOM):
        stdout = stdout[1:]

    output_file: str | None = None
    if run_dir is not None:
        artifacts_dir = run_dir / "artifacts"
        if artifacts_dir.is_dir():
            for ext in ("*.png", "*.ps", "*.pdf"):
                hits = sorted(artifacts_dir.glob(ext))
                if hits:
                    output_file = hits[0].name
                    break

    return WaterfallerResult(
        input_raw=input_raw,
        start_s=float(start_s),
        duration_s=float(duration_s),
        dm=float(dm),
        mask_file=mask_file,
        output_file=output_file,
    )
