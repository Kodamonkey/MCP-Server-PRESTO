"""``presto.rrattrap`` — wrap ``rrattrap.py`` (single-pulse event grouping).

Reads one or more ``.singlepulse`` files (from prior single_pulse_search
runs) and one ``.inf`` header, groups co-located events across DM trials,
and writes a ``groups.txt`` (+ optional per-group artifacts) into its
working directory. We stage inputs into the new run's ``artifacts/`` and
set container workdir there so groups.txt lands inside the sandbox.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from ..config import Settings, get_settings
from ..docker_backend import BackendProtocol
from ..errors import PathSecurityError
from ..executor import RunSpec, execute
from ..models import RrattrapResult, ToolRunResult
from ..parsers import rrattrap_parser
from ..path_security import resolve_run_artifact
from ..policies import check_rrattrap_input_count

log = logging.getLogger("presto_mcp.tools.rrattrap")


def run_rrattrap(
    singlepulse_files: list[str],
    inf_file: str,
    *,
    backend: BackendProtocol,
    min_group: int | None = None,
    use_dm_plan: bool = False,
    settings: Settings | None = None,
    background: bool = False,
) -> ToolRunResult[RrattrapResult]:
    """``rrattrap.py --inffile <inf> [options] *.singlepulse``.

    All inputs are ``<run_id>/artifacts/<file>`` relative to ``RUNS_DIR``.
    """
    s = settings or get_settings()
    check_rrattrap_input_count(len(singlepulse_files))

    host_sp: list[Path] = []
    names: list[str] = []
    for rel in singlepulse_files:
        host = resolve_run_artifact(rel, s.runs_dir)
        if host.suffix != ".singlepulse":
            raise PathSecurityError(
                f"rrattrap expects .singlepulse files; got {host.name}"
            )
        host_sp.append(host)
        names.append(host.name)

    if len(set(names)) != len(names):
        raise PathSecurityError(
            "rrattrap inputs must have unique filenames after staging"
        )

    host_inf = resolve_run_artifact(inf_file, s.runs_dir)
    if host_inf.suffix != ".inf":
        raise PathSecurityError(
            f"rrattrap inf_file must be a .inf; got {host_inf.name}"
        )
    inf_name = host_inf.name

    def hook(run_dir: Path, _extras: tuple[Path, ...]) -> None:
        dst_dir = run_dir / "artifacts"
        dst_dir.mkdir(parents=True, exist_ok=True)
        for host in host_sp:
            shutil.copy2(host, dst_dir / host.name)
        shutil.copy2(host_inf, dst_dir / inf_name)

    def argv_builder(
        _container_input: str, _extras: tuple[str, ...], _run_dir: Path
    ) -> list[str]:
        argv = [
            "rrattrap.py",
            "--inffile", inf_name,
        ]
        if min_group is not None:
            argv += ["--min-group", str(min_group)]
        if use_dm_plan:
            argv.append("--use-DMplan")
        argv += names
        return argv

    def parser(stdout: str, run_dir: Path) -> RrattrapResult:
        return rrattrap_parser.parse(
            stdout,
            run_dir,
            input_singlepulse_files=tuple(singlepulse_files),
            inf_file=inf_file,
        )

    inputs_extra: dict[str, str] = {
        "inf_file": inf_file,
        "input_count": str(len(singlepulse_files)),
    }
    if min_group is not None:
        inputs_extra["min_group"] = str(min_group)
    if use_dm_plan:
        inputs_extra["use_dm_plan"] = "true"

    spec = RunSpec[RrattrapResult](
        tool_name="rrattrap",
        input_file=None,
        inputs_extra=inputs_extra,
        container_input_path="",
        presto_argv_builder=argv_builder,
        parser=parser,
        timeout_s=s.default_timeout_s,
        cpus=s.default_cpus,
        memory_mb=s.default_memory_mb,
        pre_invocation_hook=hook,
        container_workdir="/outputs/artifacts",
    )
    return execute(spec, s, backend, background=background)
