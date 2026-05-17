"""``presto.single_pulse_search`` — wrap ``single_pulse_search.py``.

Reads one or more dedispersed ``.dat`` files (from prior runs) and writes
per-file ``.singlepulse`` artifacts + an optional summary ``.ps`` plot.
Inputs are staged into the current run's ``artifacts/`` so PRESTO's
"write outputs next to inputs" convention lands inside our sandbox.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from ..config import Settings, get_settings
from ..docker_backend import BackendProtocol
from ..executor import RunSpec, execute
from ..models import SinglePulseSearchResult, ToolRunResult
from ..parsers import single_pulse_search_parser
from ..path_security import resolve_run_artifact
from ..policies import check_sps_input_count, check_sps_max_width_s, check_sps_threshold

log = logging.getLogger("presto_mcp.tools.single_pulse_search")


def run_single_pulse_search(
    input_files: list[str],
    *,
    backend: BackendProtocol,
    threshold: float = 5.0,
    max_width_s: float = 0.1,
    settings: Settings | None = None,
    background: bool = False,
) -> ToolRunResult[SinglePulseSearchResult]:
    """``single_pulse_search.py -t <thr> -m <w> /outputs/artifacts/<dat1> ...``."""
    s = settings or get_settings()
    check_sps_input_count(len(input_files))
    thr = check_sps_threshold(threshold)
    mw = check_sps_max_width_s(max_width_s)

    host_paths: list[Path] = []
    names: list[str] = []
    for rel in input_files:
        host = resolve_run_artifact(rel, s.runs_dir)
        if host.suffix != ".dat":
            from ..errors import PathSecurityError

            raise PathSecurityError(
                f"single_pulse_search expects .dat files; got {host.name}"
            )
        host_paths.append(host)
        names.append(host.name)

    if len(set(names)) != len(names):
        from ..errors import PathSecurityError

        raise PathSecurityError(
            "single_pulse_search inputs must have unique filenames after staging"
        )

    def hook(run_dir: Path, _extras: tuple[Path, ...]) -> None:
        dst_dir = run_dir / "artifacts"
        dst_dir.mkdir(parents=True, exist_ok=True)
        for host in host_paths:
            shutil.copy2(host, dst_dir / host.name)
            inf = host.with_suffix(".inf")
            if inf.exists():
                shutil.copy2(inf, dst_dir / inf.name)

    def argv_builder(
        _container_input: str, _extras: tuple[str, ...], _run_dir: Path
    ) -> list[str]:
        argv = [
            "single_pulse_search.py",
            "-t", str(thr),
            "-m", str(mw),
        ]
        argv += [f"/outputs/artifacts/{n}" for n in names]
        return argv

    def parser(stdout: str, run_dir: Path) -> SinglePulseSearchResult:
        return single_pulse_search_parser.parse(
            stdout,
            run_dir,
            threshold=thr,
            max_width_s=mw,
            input_dat_files=tuple(input_files),
        )

    spec = RunSpec[SinglePulseSearchResult](
        tool_name="single_pulse_search",
        input_file=None,
        inputs_extra={
            "threshold": str(thr),
            "max_width_s": str(mw),
            "input_count": str(len(input_files)),
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
