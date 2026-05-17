"""``presto.ddplan`` — wrap ``DDplan.py`` (pure-Python DM plan).

DDplan does no file I/O: it prints a DM-trial table given observation
parameters. We still wrap it as a Docker tool for uniform sandbox/manifest
behavior.
"""

from __future__ import annotations

import logging
from pathlib import Path

from ..config import Settings, get_settings
from ..docker_backend import BackendProtocol
from ..executor import RunSpec, execute
from ..models import DDplanResult, ToolRunResult
from ..parsers import ddplan_parser
from ..policies import (
    check_ddplan_bw,
    check_ddplan_freq,
    check_ddplan_sample_time_us,
    check_dm_range,
    check_subband_count,
)

log = logging.getLogger("presto_mcp.tools.ddplan")


def run_ddplan(
    *,
    backend: BackendProtocol,
    dm_low: float,
    dm_high: float,
    freq_mhz: float,
    bw_mhz: float,
    num_channels: int,
    sample_time_us: float,
    num_subbands: int | None = None,
    settings: Settings | None = None,
    background: bool = False,
) -> ToolRunResult[DDplanResult]:
    """``DDplan.py -l <low> -d <high> -f <freq> -b <bw> -n <chans> -t <dt_s>``."""
    s = settings or get_settings()
    lo, hi = check_dm_range(dm_low, dm_high)
    f0 = check_ddplan_freq(freq_mhz)
    bw = check_ddplan_bw(bw_mhz)
    nch = check_subband_count(num_channels)
    dt_us = check_ddplan_sample_time_us(sample_time_us)
    nsub = check_subband_count(num_subbands) if num_subbands is not None else None
    dt_s = dt_us * 1e-6

    inputs_extra: dict[str, str] = {
        "dm_low": str(lo),
        "dm_high": str(hi),
        "freq_mhz": str(f0),
        "bw_mhz": str(bw),
        "num_channels": str(nch),
        "sample_time_us": str(dt_us),
    }
    if nsub is not None:
        inputs_extra["num_subbands"] = str(nsub)

    def argv_builder(
        _container_input: str, _extras: tuple[str, ...], _run_dir: Path
    ) -> list[str]:
        argv = [
            "DDplan.py",
            "-l", str(lo),
            "-d", str(hi),
            "-f", str(f0),
            "-b", str(bw),
            "-n", str(nch),
            "-t", f"{dt_s:.9g}",
            "-o", "/outputs/ddplan.eps",
        ]
        if nsub is not None:
            argv += ["-s", str(nsub)]
        return argv

    def parser(stdout: str, run_dir: Path) -> DDplanResult:
        return ddplan_parser.parse(
            stdout,
            run_dir,
            dm_low=lo,
            dm_high=hi,
            freq_mhz=f0,
            bw_mhz=bw,
            num_channels=nch,
            sample_time_us=dt_us,
        )

    spec = RunSpec[DDplanResult](
        tool_name="ddplan",
        input_file=None,
        inputs_extra=inputs_extra,
        container_input_path="",
        presto_argv_builder=argv_builder,
        parser=parser,
        timeout_s=s.default_timeout_s,
        cpus=s.default_cpus,
        memory_mb=s.default_memory_mb,
    )
    return execute(spec, s, backend, background=background)
