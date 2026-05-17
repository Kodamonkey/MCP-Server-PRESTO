"""``presto.search_bin`` — wrap ``search_bin`` (advanced binary search).

Phase-modulation / sideband search for binary pulsars on a ``.fft``. Marked
**advanced**. Conservative argv: optional ``[low_hz, high_hz]`` band passed
via ``-flo`` / ``-fhi`` when provided.
"""

from __future__ import annotations

import logging
from pathlib import Path

from ..config import Settings, get_settings
from ..docker_backend import BackendProtocol
from ..executor import RunSpec, execute
from ..models import SearchBinResult, ToolRunResult
from ..parsers import search_bin_parser
from ..policies import check_search_bin_freq_range

log = logging.getLogger("presto_mcp.tools.search_bin")


def run_search_bin(
    fft_file: str,
    *,
    backend: BackendProtocol,
    low_hz: float | None = None,
    high_hz: float | None = None,
    settings: Settings | None = None,
    background: bool = False,
) -> ToolRunResult[SearchBinResult]:
    """``search_bin [-flo <low_hz> -fhi <high_hz>] <fft>``.

    ``fft_file`` is ``<run_id>/artifacts/<file>.fft`` under ``RUNS_DIR``.
    """
    s = settings or get_settings()
    lo, hi = check_search_bin_freq_range(low_hz, high_hz)

    def argv_builder(
        container_input: str, _extras: tuple[str, ...], _run_dir: Path
    ) -> list[str]:
        argv = ["search_bin"]
        if lo is not None and hi is not None:
            argv += ["-flo", str(lo), "-fhi", str(hi)]
        argv.append(container_input)
        return argv

    def parser(stdout: str, run_dir: Path) -> SearchBinResult:
        return search_bin_parser.parse(stdout, run_dir, fft_file=fft_file)

    inputs_extra: dict[str, str] = {"fft_file": fft_file}
    if lo is not None and hi is not None:
        inputs_extra["low_hz"] = str(lo)
        inputs_extra["high_hz"] = str(hi)

    spec = RunSpec[SearchBinResult](
        tool_name="search_bin",
        input_file=fft_file,
        inputs_extra=inputs_extra,
        container_input_path="",
        presto_argv_builder=argv_builder,
        parser=parser,
        timeout_s=s.default_timeout_s,
        cpus=s.default_cpus,
        memory_mb=s.default_memory_mb,
        input_root="runs",
        container_workdir="/outputs/artifacts",
    )
    return execute(spec, s, backend, background=background)
