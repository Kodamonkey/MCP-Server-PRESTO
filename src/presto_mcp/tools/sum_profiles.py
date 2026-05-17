"""``presto.sum_profiles`` — wrap ``sum_profiles.py`` (experimental).

Average / sum many profile files (``.bestprof`` or ``.prof``) from prior runs.
Inputs come from ``RUNS_DIR``.
"""

from __future__ import annotations

import logging
from pathlib import Path

from ..config import Settings, get_settings
from ..docker_backend import BackendProtocol
from ..executor import ExtraInput, RunSpec, execute
from ..models import SumProfilesResult, ToolRunResult
from ..policies import check_profile_file_count

log = logging.getLogger("presto_mcp.tools.sum_profiles")


def run_sum_profiles(
    profile_files: list[str],
    *,
    backend: BackendProtocol,
    settings: Settings | None = None,
    background: bool = False,
) -> ToolRunResult[SumProfilesResult]:
    """``sum_profiles.py <p1> <p2> ...``.

    Each entry of ``profile_files`` is ``<run_id>/artifacts/<file>`` under
    ``RUNS_DIR``.
    """
    s = settings or get_settings()
    files = check_profile_file_count(list(profile_files))

    primary = files[0]
    extras = tuple(ExtraInput(path=p, root="runs") for p in files[1:])

    def argv_builder(
        container_input: str, extra_paths: tuple[str, ...], _run_dir: Path
    ) -> list[str]:
        return ["sum_profiles.py", container_input, *extra_paths]

    def parser(_stdout: str, run_dir: Path) -> SumProfilesResult:
        artifacts_dir = run_dir / "artifacts"
        out_prof: str | None = None
        plot: str | None = None
        notes: list[str] = []
        if artifacts_dir.is_dir():
            profs = sorted(
                p.name for p in artifacts_dir.glob("*sum*.prof")
            ) or sorted(p.name for p in artifacts_dir.glob("*.prof"))
            plots = sorted(p.name for p in artifacts_dir.glob("*.png")) + sorted(
                p.name for p in artifacts_dir.glob("*.ps")
            )
            if profs:
                out_prof = profs[0]
            if plots:
                plot = plots[0]
        if out_prof is None:
            notes.append("no summed profile produced; check stderr")
        return SumProfilesResult(
            input_profile_files=files,
            output_profile_file=out_prof,
            plot_file=plot,
            notes=notes,
        )

    spec = RunSpec[SumProfilesResult](
        tool_name="sum_profiles",
        input_file=primary,
        inputs_extra={"num_profile_files": str(len(files))},
        container_input_path="",
        presto_argv_builder=argv_builder,
        parser=parser,
        timeout_s=s.default_timeout_s,
        cpus=s.default_cpus,
        memory_mb=s.default_memory_mb,
        input_root="runs",
        extra_inputs=extras,
        container_workdir="/outputs/artifacts",
    )
    return execute(spec, s, backend, background=background)
