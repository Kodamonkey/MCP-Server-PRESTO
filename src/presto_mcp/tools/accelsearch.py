"""``presto.accelsearch`` — Fourier / acceleration candidate search on a ``.fft``.

Like :mod:`realfft`, accelsearch writes its output next to the input. We stage
a copy of the ``.fft`` and the sibling ``.inf`` into the current run's
``artifacts/`` and invoke accelsearch there.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from ..config import Settings, get_settings
from ..docker_backend import BackendProtocol
from ..errors import PathSecurityError
from ..executor import RunSpec, execute
from ..models import AccelsearchResult, ToolRunResult
from ..parsers import accelsearch_parser
from ..path_security import resolve_run_artifact
from ..policies import check_numharm, check_zmax

log = logging.getLogger("presto_mcp.tools.accelsearch")


def run_accelsearch(
    input_file: str,
    *,
    backend: BackendProtocol,
    zmax: int = 200,
    numharm: int = 8,
    settings: Settings | None = None,
    background: bool = False,
) -> ToolRunResult[AccelsearchResult]:
    """``accelsearch -zmax <z> -numharm <h> /outputs/artifacts/<input>.fft``."""
    s = settings or get_settings()
    z = check_zmax(zmax)
    nh = check_numharm(numharm)
    host_fft = resolve_run_artifact(input_file, s.runs_dir)
    if host_fft.suffix != ".fft":
        raise PathSecurityError(
            f"accelsearch expects a .fft file; got {host_fft.name}"
        )
    name = host_fft.name

    def hook(run_dir: Path, _extras: tuple[Path, ...]) -> None:
        dst_dir = run_dir / "artifacts"
        dst_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(host_fft, dst_dir / name)
        inf = host_fft.with_suffix(".inf")
        if inf.exists():
            shutil.copy2(inf, dst_dir / inf.name)

    def argv_builder(
        _container_input: str, _extras: tuple[str, ...], _run_dir: Path
    ) -> list[str]:
        return [
            "accelsearch",
            "-zmax", str(z),
            "-numharm", str(nh),
            f"/outputs/artifacts/{name}",
        ]

    def parser(stdout: str, run_dir: Path) -> AccelsearchResult:
        return accelsearch_parser.parse(
            stdout, run_dir, zmax=z, numharm=nh, input_fft=name
        )

    spec = RunSpec[AccelsearchResult](
        tool_name="accelsearch",
        input_file=None,
        inputs_extra={
            "zmax": str(z),
            "numharm": str(nh),
            "input_fft": input_file,
        },
        container_input_path="",
        presto_argv_builder=argv_builder,
        parser=parser,
        timeout_s=s.default_timeout_s,
        cpus=s.default_cpus,
        memory_mb=s.default_memory_mb,
        pre_invocation_hook=hook,
    )
    return execute(spec, s, backend, background=background)
