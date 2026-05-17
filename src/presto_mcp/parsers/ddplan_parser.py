"""Parse PRESTO ``DDplan.py`` stdout into a typed :class:`DDplanResult`.

DDplan.py prints a header describing the observation, then a table of
dedispersion passes:

    Low DM    High DM    dDM     DownSamp    dsubDM    #DMs   WorkFract
    -----     -------    ---     --------    ------    ----   --------
    0.000     50.000     0.10    1           4.00      500    0.5000
    ...
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from ..errors import ParserError
from ..models import DDplanPass, DDplanResult

log = logging.getLogger("presto_mcp.parsers.ddplan")

_BOM = "﻿"

# Lines that look like:  "0.000   50.000   0.10   1   4.00   500   0.5"
_ROW = re.compile(
    r"^\s*([-+]?\d+\.\d+)\s+([-+]?\d+\.\d+)\s+([\d.]+)\s+(\d+)\s+([\d.]+)\s+(\d+)\b"
)


def parse(
    stdout: str,
    _run_dir: Path | None = None,
    *,
    dm_low: float = 0.0,
    dm_high: float = 0.0,
    freq_mhz: float = 0.0,
    bw_mhz: float = 0.0,
    num_channels: int = 0,
    sample_time_us: float = 0.0,
) -> DDplanResult:
    if not isinstance(stdout, str):
        raise ParserError(f"stdout must be str, got {type(stdout).__name__}")
    if stdout.startswith(_BOM):
        stdout = stdout[1:]
    if not stdout.strip():
        raise ParserError("DDplan stdout is empty")

    passes: list[DDplanPass] = []
    total_dms = 0
    for line in stdout.splitlines():
        m = _ROW.match(line)
        if not m:
            continue
        try:
            low = float(m.group(1))
            step = float(m.group(3))
            downsamp = int(m.group(4))
            dms = int(m.group(6))
        except ValueError:
            continue
        passes.append(
            DDplanPass(
                low_dm=low,
                dm_step=step,
                dms_per_call=dms,
                num_calls=1,
                downsamp=downsamp,
            )
        )
        total_dms += dms

    if not passes:
        raise ParserError("DDplan stdout contained no recognizable plan rows")

    return DDplanResult(
        dm_low=float(dm_low),
        dm_high=float(dm_high),
        num_dms=total_dms,
        freq_mhz=float(freq_mhz),
        bw_mhz=float(bw_mhz),
        num_channels=int(num_channels),
        sample_time_us=float(sample_time_us),
        passes=passes,
    )
