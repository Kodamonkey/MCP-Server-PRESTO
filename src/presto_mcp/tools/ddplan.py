"""``presto.ddplan`` — wrap ``DDplan.py`` (DM-trial planning).

Two modes:

* **Parametric** (original): obs params are given explicitly as flags. DDplan
  does no file I/O and just prints a DM-trial table.
* **input_file** (added): a raw filterbank/PSRFITS path is supplied as an MCP
  convenience. The file is mounted read-only and appended as the final
  *positional* argument so DDplan.py can infer ``dt/fctr/bw/numchan`` from it.
  ``input_file`` is never passed as ``--input-file`` — only positionally.
  Any explicit obs params still go through as flags and override file-derived
  values.

``write_dedisp_script`` adds ``-w`` (capability-gated against ``DDplan.py -h``)
and requires ``input_file`` — DDplan.py needs a raw filename to emit a usable
``dedisp_*.py`` script.
"""

from __future__ import annotations

import logging
from pathlib import Path

from ..config import Settings, get_settings
from ..docker_backend import BackendProtocol
from ..errors import DockerInvocationError, PolicyViolationError
from ..executor import RunSpec, execute
from ..models import DDplanResult, ToolRunResult
from ..parsers import ddplan_parser
from ..path_security import is_run_artifact_path
from ..policies import (
    check_ddplan_bw,
    check_ddplan_freq,
    check_ddplan_sample_time_us,
    check_dm_range,
    check_output_prefix,
    check_subband_count,
)
from ..runtime_checks import check_binary_help, check_flag_supported

log = logging.getLogger("presto_mcp.tools.ddplan")

_DEDISP_FLAG = "-w"


def run_ddplan(
    *,
    backend: BackendProtocol,
    dm_low: float,
    dm_high: float,
    freq_mhz: float | None = None,
    bw_mhz: float | None = None,
    num_channels: int | None = None,
    sample_time_us: float | None = None,
    num_subbands: int | None = None,
    input_file: str | None = None,
    write_dedisp_script: bool = False,
    output_prefix: str | None = None,
    settings: Settings | None = None,
    background: bool = False,
) -> ToolRunResult[DDplanResult]:
    """``DDplan.py -l <low> -d <high> [-f -b -n -t -s -w] [<input_file>]``."""
    s = settings or get_settings()
    lo, hi = check_dm_range(dm_low, dm_high)

    if input_file is None:
        missing = [
            name
            for name, value in (
                ("freq_mhz", freq_mhz),
                ("bw_mhz", bw_mhz),
                ("num_channels", num_channels),
                ("sample_time_us", sample_time_us),
            )
            if value is None
        ]
        if missing:
            raise PolicyViolationError(
                "ddplan parametric mode requires "
                f"{', '.join(missing)}; or supply input_file so DDplan.py can "
                "infer the observation parameters from the raw file."
            )

    f0 = check_ddplan_freq(freq_mhz) if freq_mhz is not None else None
    bw = check_ddplan_bw(bw_mhz) if bw_mhz is not None else None
    nch = check_subband_count(num_channels) if num_channels is not None else None
    dt_us = (
        check_ddplan_sample_time_us(sample_time_us)
        if sample_time_us is not None
        else None
    )
    nsub = check_subband_count(num_subbands) if num_subbands is not None else None
    prefix = check_output_prefix(output_prefix) if output_prefix else "ddplan"

    if write_dedisp_script and input_file is None:
        raise PolicyViolationError(
            "write_dedisp_script=true requires input_file: DDplan.py -w needs a "
            "raw input filename to emit a usable dedisp_*.py script."
        )

    if write_dedisp_script:
        help_check, help_text = check_binary_help(backend, s, "DDplan.py")
        if help_check.status == "OK" and not check_flag_supported(
            help_text, _DEDISP_FLAG
        ):
            raise DockerInvocationError(
                f"DDplan.py in image {s.image} does not support the "
                f"`{_DEDISP_FLAG}` (write dedisp script) flag. Omit "
                "write_dedisp_script, or use a PRESTO image whose DDplan.py "
                "provides it. Run presto.validate_environment for details."
            )
        # help_check UNKNOWN -> fail-open: let the real run surface any error.

    input_root = (
        "runs" if input_file is not None and is_run_artifact_path(input_file)
        else "data"
    )

    inputs_extra: dict[str, str] = {
        "dm_low": str(lo),
        "dm_high": str(hi),
        "write_dedisp_script": str(write_dedisp_script).lower(),
        "output_prefix": prefix,
    }
    for key, value in (
        ("freq_mhz", f0),
        ("bw_mhz", bw),
        ("num_channels", nch),
        ("sample_time_us", dt_us),
        ("num_subbands", nsub),
    ):
        if value is not None:
            inputs_extra[key] = str(value)

    def argv_builder(
        container_input: str, _extras: tuple[str, ...], _run_dir: Path
    ) -> list[str]:
        argv = ["DDplan.py", "-l", str(lo), "-d", str(hi)]
        if f0 is not None:
            argv += ["-f", str(f0)]
        if bw is not None:
            argv += ["-b", str(bw)]
        if nch is not None:
            argv += ["-n", str(nch)]
        if dt_us is not None:
            argv += ["-t", f"{dt_us * 1e-6:.9g}"]
        if nsub is not None:
            argv += ["-s", str(nsub)]
        argv += ["-o", f"/outputs/artifacts/{prefix}.eps"]
        if write_dedisp_script:
            argv.append(_DEDISP_FLAG)
        if container_input:
            argv.append(container_input)
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
            input_file=input_file,
        )

    spec = RunSpec[DDplanResult](
        tool_name="ddplan",
        input_file=input_file,
        inputs_extra=inputs_extra,
        container_input_path="",
        input_root=input_root,
        presto_argv_builder=argv_builder,
        parser=parser,
        timeout_s=s.default_timeout_s,
        cpus=s.default_cpus,
        memory_mb=s.default_memory_mb,
        container_workdir="/outputs/artifacts",
    )
    return execute(spec, s, backend, background=background)
