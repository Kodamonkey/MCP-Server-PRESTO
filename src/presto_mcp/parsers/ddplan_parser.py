"""Parse PRESTO ``DDplan.py`` stdout into a typed :class:`DDplanResult`.

DDplan.py prints a header describing the observation, then a table of
dedispersion passes:

    Low DM    High DM    dDM     DownSamp    dsubDM    #DMs   WorkFract
    -----     -------    ---     --------    ------    ----   --------
    0.000     50.000     0.10    1           4.00      500    0.5000
    ...

When run with ``-o`` it also writes a plot (``.eps``/``.png``) and with ``-w``
a ``dedisp_*.py`` script — both into the run's ``artifacts/``.
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


def _scan_artifacts(run_dir: Path) -> tuple[str | None, str | None, list[str]]:
    """Return (plot_file, dedisp_script, notes) by scanning artifacts/."""
    notes: list[str] = []
    plot_file: str | None = None
    dedisp_script: str | None = None
    artifacts_dir = run_dir / "artifacts"
    if not artifacts_dir.is_dir():
        return None, None, notes
    plots = sorted(
        p.name
        for p in artifacts_dir.iterdir()
        if p.is_file() and p.suffix.lower() in {".eps", ".png", ".ps"}
    )
    if plots:
        plot_file = plots[0]
    dedisp = sorted(
        p.name
        for p in artifacts_dir.iterdir()
        if p.is_file() and p.name.startswith("dedisp") and p.suffix == ".py"
    )
    if dedisp:
        dedisp_script = dedisp[0]
    return plot_file, dedisp_script, notes


def parse(
    stdout: str,
    run_dir: Path | None = None,
    *,
    dm_low: float = 0.0,
    dm_high: float = 0.0,
    freq_mhz: float | None = None,
    bw_mhz: float | None = None,
    num_channels: int | None = None,
    sample_time_us: float | None = None,
    input_file: str | None = None,
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

    plot_file: str | None = None
    dedisp_script: str | None = None
    notes: list[str] = []
    if run_dir is not None:
        plot_file, dedisp_script, notes = _scan_artifacts(run_dir)

    return DDplanResult(
        dm_low=float(dm_low),
        dm_high=float(dm_high),
        num_dms=total_dms,
        freq_mhz=float(freq_mhz) if freq_mhz is not None else None,
        bw_mhz=float(bw_mhz) if bw_mhz is not None else None,
        num_channels=int(num_channels) if num_channels is not None else None,
        sample_time_us=float(sample_time_us) if sample_time_us is not None else None,
        input_file=input_file,
        passes=passes,
        plot_file=plot_file,
        dedisp_script=dedisp_script,
        notes=notes,
    )
