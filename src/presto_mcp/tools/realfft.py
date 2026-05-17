"""``presto.realfft`` — FFT a ``.dat`` into a ``.fft`` (and a copy of ``.inf``).

realfft writes its output next to the input. The input lives in a prior run's
``artifacts/`` (read-only at ``/runs``), so we stage a copy of the ``.dat``
and its sibling ``.inf`` into the current run's ``artifacts/`` and invoke
realfft against ``/outputs/artifacts/<name>.dat``.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from ..config import Settings, get_settings
from ..docker_backend import BackendProtocol
from ..executor import RunSpec, execute
from ..models import RealfftResult, ToolRunResult
from ..parsers import realfft_parser
from ..path_security import resolve_run_artifact

log = logging.getLogger("presto_mcp.tools.realfft")


def run_realfft(
    input_file: str,
    *,
    backend: BackendProtocol,
    settings: Settings | None = None,
    background: bool = False,
) -> ToolRunResult[RealfftResult]:
    """``realfft /outputs/artifacts/<input>.dat``.

    ``input_file`` is interpreted as ``<run_id>/artifacts/<file>.dat``
    relative to ``RUNS_DIR``.
    """
    s = settings or get_settings()
    host_dat = resolve_run_artifact(input_file, s.runs_dir)
    if host_dat.suffix != ".dat":
        from ..errors import PathSecurityError

        raise PathSecurityError(
            f"realfft expects a .dat file; got {host_dat.name}"
        )
    name = host_dat.name

    def hook(run_dir: Path, _extras: tuple[Path, ...]) -> None:
        dst_dir = run_dir / "artifacts"
        dst_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(host_dat, dst_dir / name)
        inf = host_dat.with_suffix(".inf")
        if inf.exists():
            shutil.copy2(inf, dst_dir / inf.name)

    def argv_builder(
        _container_input: str, _extras: tuple[str, ...], _run_dir: Path
    ) -> list[str]:
        return ["realfft", f"/outputs/artifacts/{name}"]

    def parser(stdout: str, run_dir: Path) -> RealfftResult:
        return realfft_parser.parse(stdout, run_dir, input_dat=name)

    spec = RunSpec[RealfftResult](
        tool_name="realfft",
        input_file=None,
        inputs_extra={"input_dat": input_file},
        container_input_path="",
        presto_argv_builder=argv_builder,
        parser=parser,
        timeout_s=s.default_timeout_s,
        cpus=s.default_cpus,
        memory_mb=s.default_memory_mb,
        pre_invocation_hook=hook,
    )
    return execute(spec, s, backend, background=background)
