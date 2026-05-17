"""``presto.rfifind`` — wraps ``rfifind -time <t> -o /outputs/<prefix> /data/<file>``."""

from __future__ import annotations

import logging
from pathlib import Path

from ..config import Settings, get_settings
from ..docker_backend import BackendProtocol
from ..executor import RunSpec, execute
from ..models import RfifindSummary, ToolRunResult
from ..parsers import rfifind_parser
from ..policies import check_output_prefix, check_rfifind_time

log = logging.getLogger("presto_mcp.tools.rfifind")

DEFAULT_PREFIX = "rfi"


def run_rfifind(
    input_file: str,
    *,
    backend: BackendProtocol,
    time: float = 2.0,
    output_prefix: str | None = None,
    settings: Settings | None = None,
    background: bool = False,
) -> ToolRunResult[RfifindSummary]:
    """Run ``rfifind`` on a file under ``DATA_DIR``."""
    s = settings or get_settings()
    t = check_rfifind_time(time)
    prefix = check_output_prefix(output_prefix or DEFAULT_PREFIX)

    def argv_builder(
        container_input: str, _extras: tuple[str, ...], _run_dir: Path
    ) -> list[str]:
        return ["rfifind", "-time", str(t), "-o", f"/outputs/artifacts/{prefix}", container_input]

    def parser(stdout: str, run_dir: Path) -> RfifindSummary:
        return rfifind_parser.parse(stdout, run_dir, time_s=t)

    spec = RunSpec[RfifindSummary](
        tool_name="rfifind",
        input_file=input_file,
        inputs_extra={"time_s": str(t), "output_prefix": prefix},
        container_input_path="",
        presto_argv_builder=argv_builder,
        parser=parser,
        timeout_s=s.default_timeout_s,
        cpus=s.default_cpus,
        memory_mb=s.default_memory_mb,
    )
    return execute(spec, s, backend, background=background)
