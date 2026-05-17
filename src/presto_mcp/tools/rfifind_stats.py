"""``presto.rfifind_stats`` — wrap ``rfifind_stats.py``.

Summarize a prior rfifind run (``.stats`` + optional ``.mask``) into a
structured list of bad channels and bad intervals. Inputs come from a prior
run's artifacts (``input_root="runs"``).
"""

from __future__ import annotations

import logging
from pathlib import Path

from ..config import Settings, get_settings
from ..docker_backend import BackendProtocol
from ..executor import ExtraInput, RunSpec, execute
from ..models import RfifindStatsResult, ToolRunResult
from ..parsers import rfifind_stats_parser

log = logging.getLogger("presto_mcp.tools.rfifind_stats")


def run_rfifind_stats(
    stats_file: str,
    *,
    backend: BackendProtocol,
    mask_file: str | None = None,
    settings: Settings | None = None,
    background: bool = False,
) -> ToolRunResult[RfifindStatsResult]:
    """``rfifind_stats.py <stats> [<mask>]``.

    ``stats_file`` is interpreted as ``<run_id>/artifacts/<file>.stats`` under
    ``RUNS_DIR``. Optional ``mask_file`` is also under ``RUNS_DIR``.
    """
    s = settings or get_settings()

    extras: tuple[ExtraInput, ...] = ()
    if mask_file is not None:
        extras = (ExtraInput(path=mask_file, root="runs"),)

    def argv_builder(
        container_input: str, extra_paths: tuple[str, ...], _run_dir: Path
    ) -> list[str]:
        argv = ["rfifind_stats.py", container_input]
        if extra_paths:
            argv.append(extra_paths[0])
        return argv

    def parser(stdout: str, run_dir: Path) -> RfifindStatsResult:
        return rfifind_stats_parser.parse(
            stdout, run_dir, stats_file=stats_file, mask_file=mask_file
        )

    inputs_extra: dict[str, str] = {"stats_file": stats_file}
    if mask_file is not None:
        inputs_extra["mask_file"] = mask_file

    spec = RunSpec[RfifindStatsResult](
        tool_name="rfifind_stats",
        input_file=stats_file,
        inputs_extra=inputs_extra,
        container_input_path="",
        presto_argv_builder=argv_builder,
        parser=parser,
        timeout_s=s.default_timeout_s,
        cpus=s.default_cpus,
        memory_mb=s.default_memory_mb,
        input_root="runs",
        extra_inputs=extras,
    )
    return execute(spec, s, backend, background=background)
