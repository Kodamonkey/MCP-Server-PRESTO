"""``presto.plot_spd`` — wrap ``plot_spd.py`` (single-pulse diagnostic plot).

Reads a ``.spd`` (numpy binary, from prior make_spd run) plus optional
``.singlepulse`` files and writes a PNG (or PS) diagnostic plot. Default
output basename is ``spdplot``. We invoke with workdir
``/outputs/artifacts`` so the image lands inside the run sandbox.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from ..config import Settings, get_settings
from ..docker_backend import BackendProtocol
from ..errors import PathSecurityError
from ..executor import RunSpec, execute
from ..models import PlotSpdResult, ToolRunResult
from ..parsers import plot_spd_parser
from ..path_security import resolve_run_artifact
from ..policies import check_output_prefix

log = logging.getLogger("presto_mcp.tools.plot_spd")


def run_plot_spd(
    input_spd: str,
    *,
    backend: BackendProtocol,
    singlepulse_files: list[str] | None = None,
    output_prefix: str | None = None,
    just_waterfall: bool = False,
    settings: Settings | None = None,
    background: bool = False,
) -> ToolRunResult[PlotSpdResult]:
    """``plot_spd.py [--just-waterfall] -o <prefix> <spd> [<sp>...]``.

    ``input_spd`` is ``<run_id>/artifacts/<file>.spd`` relative to ``RUNS_DIR``.
    Optional ``singlepulse_files`` are also ``<run_id>/artifacts/...`` paths.
    """
    s = settings or get_settings()
    prefix = check_output_prefix(output_prefix) if output_prefix else "spdplot"

    host_spd = resolve_run_artifact(input_spd, s.runs_dir)
    if host_spd.suffix != ".spd":
        raise PathSecurityError(
            f"plot_spd expects a .spd file; got {host_spd.name}"
        )
    spd_name = host_spd.name

    sp_files = singlepulse_files or []
    host_sp: list[Path] = []
    sp_names: list[str] = []
    for rel in sp_files:
        host = resolve_run_artifact(rel, s.runs_dir)
        if host.suffix != ".singlepulse":
            raise PathSecurityError(
                f"plot_spd singlepulse inputs must be .singlepulse; got {host.name}"
            )
        host_sp.append(host)
        sp_names.append(host.name)

    if len(set(sp_names)) != len(sp_names):
        raise PathSecurityError(
            "plot_spd singlepulse inputs must have unique filenames after staging"
        )

    def hook(run_dir: Path, _extras: tuple[Path, ...]) -> None:
        dst_dir = run_dir / "artifacts"
        dst_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(host_spd, dst_dir / spd_name)
        for host in host_sp:
            shutil.copy2(host, dst_dir / host.name)

    def argv_builder(
        _container_input: str, _extras: tuple[str, ...], _run_dir: Path
    ) -> list[str]:
        argv = ["plot_spd.py", "-o", prefix]
        if just_waterfall:
            argv.append("--just-waterfall")
        argv.append(spd_name)
        argv += sp_names
        return argv

    def parser(stdout: str, run_dir: Path) -> PlotSpdResult:
        return plot_spd_parser.parse(stdout, run_dir, input_spd=input_spd)

    inputs_extra: dict[str, str] = {
        "input_spd": input_spd,
        "output_prefix": prefix,
        "just_waterfall": "true" if just_waterfall else "false",
    }
    if sp_files:
        inputs_extra["sp_count"] = str(len(sp_files))

    spec = RunSpec[PlotSpdResult](
        tool_name="plot_spd",
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
