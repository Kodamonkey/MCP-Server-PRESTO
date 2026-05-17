"""``presto.prepsubband`` — batch dedisperse a DM range to many ``.dat`` files."""

from __future__ import annotations

import logging
from pathlib import Path

from ..config import Settings, get_settings
from ..docker_backend import BackendProtocol
from ..executor import ExtraInput, RunSpec, execute
from ..models import PrepsubbandResult, ToolRunResult
from ..parsers import prepsubband_parser
from ..policies import (
    check_dm,
    check_dm_step,
    check_num_dms,
    check_output_prefix,
    check_subband_count,
)

log = logging.getLogger("presto_mcp.tools.prepsubband")

DEFAULT_PREFIX = "sub"


def run_prepsubband(
    input_file: str,
    *,
    backend: BackendProtocol,
    dm_low: float,
    dm_step: float,
    num_dms: int,
    num_subbands: int,
    output_prefix: str | None = None,
    mask_file: str | None = None,
    settings: Settings | None = None,
    background: bool = False,
) -> ToolRunResult[PrepsubbandResult]:
    """``prepsubband -lodm <low> -dmstep <step> -numdms <N> -nsub <S> -o <prefix> <input>``."""
    s = settings or get_settings()
    lo = check_dm(dm_low)
    step = check_dm_step(dm_step)
    ndm = check_num_dms(num_dms)
    nsub = check_subband_count(num_subbands)
    prefix = check_output_prefix(output_prefix or DEFAULT_PREFIX)

    extras: tuple[ExtraInput, ...] = ()
    inputs_extra: dict[str, str] = {
        "dm_low": str(lo),
        "dm_step": str(step),
        "num_dms": str(ndm),
        "num_subbands": str(nsub),
        "output_prefix": prefix,
    }
    if mask_file:
        extras = (ExtraInput(path=mask_file, root="data"),)
        inputs_extra["mask_file"] = mask_file

    def argv_builder(
        container_input: str, extra_paths: tuple[str, ...], _run_dir: Path
    ) -> list[str]:
        argv = [
            "prepsubband",
            "-lodm", str(lo),
            "-dmstep", str(step),
            "-numdms", str(ndm),
            "-nsub", str(nsub),
            "-o", f"/outputs/artifacts/{prefix}",
        ]
        if extra_paths:
            argv += ["-mask", extra_paths[0]]
        argv.append(container_input)
        return argv

    def parser(stdout: str, run_dir: Path) -> PrepsubbandResult:
        return prepsubband_parser.parse(
            stdout,
            run_dir,
            dm_low=lo,
            dm_step=step,
            num_dms=ndm,
            num_subbands=nsub,
            output_prefix=prefix,
        )

    spec = RunSpec[PrepsubbandResult](
        tool_name="prepsubband",
        input_file=input_file,
        inputs_extra=inputs_extra,
        container_input_path="",
        presto_argv_builder=argv_builder,
        parser=parser,
        timeout_s=s.default_timeout_s,
        cpus=s.default_cpus,
        memory_mb=s.default_memory_mb,
        extra_inputs=extras,
    )
    return execute(spec, s, backend, background=background)
