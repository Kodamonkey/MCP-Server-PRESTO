"""``presto.prepdata`` — dedisperse a single DM to a ``.dat`` time series."""

from __future__ import annotations

import logging
from pathlib import Path

from ..config import Settings, get_settings
from ..docker_backend import BackendProtocol
from ..executor import ExtraInput, RunSpec, execute, extra_input_for
from ..models import PrepdataResult, ToolRunResult
from ..parsers import prepdata_parser
from ..policies import check_dm, check_output_prefix

log = logging.getLogger("presto_mcp.tools.prepdata")

DEFAULT_PREFIX = "prep"


def run_prepdata(
    input_file: str,
    dm: float,
    *,
    backend: BackendProtocol,
    output_prefix: str | None = None,
    mask_file: str | None = None,
    settings: Settings | None = None,
    background: bool = False,
) -> ToolRunResult[PrepdataResult]:
    """``prepdata -dm <dm> -o /outputs/artifacts/<prefix> /data/<input>``.

    Optional ``mask_file`` can be either a path relative to ``DATA_DIR`` or a
    ``<run_id>/artifacts/<file>.mask`` produced by a prior ``rfifind`` run; the
    root is detected from the path shape. Using a prior-run artifact avoids
    copying the mask + its companion files (``.inf``, ``.bytemask``, ``.rfi``,
    ``.stats``) into ``DATA_DIR`` — PRESTO reads them from ``/runs`` instead.
    """
    s = settings or get_settings()
    d = check_dm(dm)
    prefix = check_output_prefix(output_prefix or DEFAULT_PREFIX)

    extras: tuple[ExtraInput, ...] = ()
    inputs_extra: dict[str, str] = {"dm": str(d), "output_prefix": prefix}
    if mask_file:
        extras = (extra_input_for(mask_file),)
        inputs_extra["mask_file"] = mask_file

    def argv_builder(
        container_input: str, extra_paths: tuple[str, ...], _run_dir: Path
    ) -> list[str]:
        argv = [
            "prepdata",
            "-dm", str(d),
            "-o", f"/outputs/artifacts/{prefix}",
        ]
        if extra_paths:
            argv += ["-mask", extra_paths[0]]
        argv.append(container_input)
        return argv

    def parser(stdout: str, run_dir: Path) -> PrepdataResult:
        return prepdata_parser.parse(stdout, run_dir, dm=d, output_prefix=prefix)

    spec = RunSpec[PrepdataResult](
        tool_name="prepdata",
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
