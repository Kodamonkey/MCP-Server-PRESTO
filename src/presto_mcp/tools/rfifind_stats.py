"""``presto.rfifind_stats`` — wrap ``rfifind_stats.py``.

Summarize a prior rfifind run (``.stats`` + optional ``.mask``) into a
structured list of bad channels and bad intervals. Inputs come from a prior
run's artifacts (``input_root="runs"``).
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from ..config import Settings, get_settings
from ..docker_backend import BackendProtocol
from ..executor import RunSpec, execute
from ..models import RfifindStatsResult, ToolRunResult
from ..parsers import rfifind_stats_parser
from ..path_security import resolve_run_artifact

log = logging.getLogger("presto_mcp.tools.rfifind_stats")


def run_rfifind_stats(
    stats_file: str,
    *,
    backend: BackendProtocol,
    mask_file: str | None = None,
    settings: Settings | None = None,
    background: bool = False,
) -> ToolRunResult[RfifindStatsResult]:
    """``rfifind_stats.py <stats>``.

    ``stats_file`` is interpreted as ``<run_id>/artifacts/<file>.stats`` under
    ``RUNS_DIR``. Optional ``mask_file`` is also under ``RUNS_DIR``.
    """
    s = settings or get_settings()

    host_stats = resolve_run_artifact(stats_file, s.runs_dir)
    stats_name = host_stats.name
    host_inf = host_stats.with_suffix(".inf")
    inf_name = host_inf.name
    host_mask: Path | None = None
    mask_name: str | None = None
    if mask_file is not None:
        host_mask = resolve_run_artifact(mask_file, s.runs_dir)
        mask_name = host_mask.name

    def hook(run_dir: Path, _extras: tuple[Path, ...]) -> None:
        dst_dir = run_dir / "artifacts"
        dst_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(host_stats, dst_dir / stats_name)
        # rfifind_stats.py reads sibling .inf derived from basename.
        if host_inf.exists():
            shutil.copy2(host_inf, dst_dir / inf_name)
        if host_mask is not None and mask_name is not None:
            shutil.copy2(host_mask, dst_dir / mask_name)

    def argv_builder(
        container_input: str, extra_paths: tuple[str, ...], _run_dir: Path
    ) -> list[str]:
        # PRESTO's rfifind_stats.py accepts a single positional input.
        # Keep mask_file for validation/metadata parity, but do not pass it to argv.
        _ = container_input, extra_paths
        return ["rfifind_stats.py", f"/outputs/artifacts/{stats_name}"]

    def parser(stdout: str, run_dir: Path) -> RfifindStatsResult:
        return rfifind_stats_parser.parse(
            stdout, run_dir, stats_file=stats_file, mask_file=mask_file
        )

    inputs_extra: dict[str, str] = {"stats_file": stats_file}
    if mask_file is not None:
        inputs_extra["mask_file"] = mask_file

    spec = RunSpec[RfifindStatsResult](
        tool_name="rfifind_stats",
        input_file=stats_file,
        inputs_extra=inputs_extra,
        container_input_path="",
        presto_argv_builder=argv_builder,
        parser=parser,
        timeout_s=s.default_timeout_s,
        cpus=s.default_cpus,
        memory_mb=s.default_memory_mb,
        input_root="runs",
        pre_invocation_hook=hook,
        container_workdir="/outputs/artifacts",
    )
    return execute(spec, s, backend, background=background)
