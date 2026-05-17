"""``presto.readfile`` — wraps ``readfile /data/<input_file>``."""

from __future__ import annotations

import logging
from pathlib import Path

from ..config import Settings, get_settings
from ..docker_backend import BackendProtocol
from ..executor import RunSpec, execute
from ..models import ReadfileMetadata, ToolRunResult
from ..parsers import readfile_parser

log = logging.getLogger("presto_mcp.tools.readfile")


def _argv_builder(
    container_input: str, _extras: tuple[str, ...], _run_dir: Path
) -> list[str]:
    return ["readfile", container_input]


def _parser(stdout: str, run_dir: Path) -> ReadfileMetadata:
    return readfile_parser.parse(stdout, run_dir)


def run_readfile(
    input_file: str,
    *,
    backend: BackendProtocol,
    settings: Settings | None = None,
    background: bool = False,
) -> ToolRunResult[ReadfileMetadata]:
    """Run ``readfile`` on a file under ``DATA_DIR`` and return parsed metadata."""
    s = settings or get_settings()
    spec = RunSpec[ReadfileMetadata](
        tool_name="readfile",
        input_file=input_file,
        inputs_extra={},
        container_input_path="",  # filled by executor via _to_container_path
        presto_argv_builder=_argv_builder,
        parser=_parser,
        timeout_s=s.default_timeout_s,
        cpus=s.default_cpus,
        memory_mb=s.default_memory_mb,
    )
    return execute(spec, s, backend, background=background)
