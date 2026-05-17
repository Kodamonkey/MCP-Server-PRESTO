"""``presto.weights_to_ignorechan`` — wrap ``weights_to_ignorechan.py``.

Convert a ``.weights`` (or ``.mask``) artifact from a prior run into an
ignorechan list. Stdout is captured + parsed; the script may also write an
artifact under the new run's artifacts/. Marked **experimental** until
verified against the configured image.
"""

from __future__ import annotations

import logging
from pathlib import Path

from ..config import Settings, get_settings
from ..docker_backend import BackendProtocol
from ..executor import RunSpec, execute
from ..models import ToolRunResult, WeightsToIgnorechanResult
from ..parsers import weights_to_ignorechan_parser

log = logging.getLogger("presto_mcp.tools.weights_to_ignorechan")


def run_weights_to_ignorechan(
    weights_file: str,
    *,
    backend: BackendProtocol,
    threshold: float | None = None,
    settings: Settings | None = None,
    background: bool = False,
) -> ToolRunResult[WeightsToIgnorechanResult]:
    """``weights_to_ignorechan.py [-t <threshold>] <weights>``.

    ``weights_file`` is ``<run_id>/artifacts/<file>.weights`` (or ``.mask``)
    under ``RUNS_DIR``.
    """
    s = settings or get_settings()
    thr: float | None = None
    if threshold is not None:
        thr = float(threshold)
        if not (0.0 <= thr <= 1.0):
            from ..errors import PolicyViolationError

            raise PolicyViolationError(
                f"weights_to_ignorechan threshold {threshold} outside [0, 1]"
            )

    def argv_builder(
        container_input: str, _extras: tuple[str, ...], _run_dir: Path
    ) -> list[str]:
        argv = ["weights_to_ignorechan.py"]
        if thr is not None:
            argv += ["-t", str(thr)]
        argv.append(container_input)
        return argv

    def parser(stdout: str, run_dir: Path) -> WeightsToIgnorechanResult:
        return weights_to_ignorechan_parser.parse(
            stdout, run_dir, weights_file=weights_file
        )

    inputs_extra: dict[str, str] = {"weights_file": weights_file}
    if thr is not None:
        inputs_extra["threshold"] = str(thr)

    spec = RunSpec[WeightsToIgnorechanResult](
        tool_name="weights_to_ignorechan",
        input_file=weights_file,
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
