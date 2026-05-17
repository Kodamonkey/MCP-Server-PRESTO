"""``presto.pfd2png`` — wrap ``pfd2png.sh`` (experimental).

Converts a folded ``.pfd`` to PNG. The script is not part of every PRESTO
distribution; the tool is marked **experimental** and reports a helpful note
if the binary is missing.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from ..config import Settings, get_settings
from ..docker_backend import BackendProtocol
from ..executor import RunSpec, execute
from ..models import Pfd2PngResult, ToolRunResult

log = logging.getLogger("presto_mcp.tools.pfd2png")


def run_pfd2png(
    pfd_file: str,
    *,
    backend: BackendProtocol,
    settings: Settings | None = None,
    background: bool = False,
) -> ToolRunResult[Pfd2PngResult]:
    """``pfd2png.sh <pfd>``.

    ``pfd_file`` is ``<run_id>/artifacts/<file>.pfd`` under ``RUNS_DIR``. The
    .pfd is read read-only from ``/runs``; we stage a copy into the new run's
    artifacts/ dir so the script's sibling-write outputs land under
    ``/outputs/artifacts``.
    """
    s = settings or get_settings()

    pfd_basename = Path(pfd_file).name

    def _stage_pfd(run_dir: Path, _extras: tuple[Path, ...]) -> None:
        src = s.runs_dir / pfd_file
        if not src.is_file():
            return
        dst = run_dir / "artifacts" / pfd_basename
        shutil.copy(src, dst)

    def argv_builder(
        _container_input: str, _extras: tuple[str, ...], _run_dir: Path
    ) -> list[str]:
        return ["pfd2png.sh", pfd_basename]

    def parser(stdout: str, run_dir: Path) -> Pfd2PngResult:
        artifacts_dir = run_dir / "artifacts"
        png: str | None = None
        ps: str | None = None
        notes: list[str] = []
        if artifacts_dir.is_dir():
            pngs = sorted(p.name for p in artifacts_dir.glob("*.png"))
            pss = sorted(p.name for p in artifacts_dir.glob("*.ps"))
            if pngs:
                png = pngs[0]
            if pss:
                ps = pss[0]
        if png is None and ps is None:
            lowered = stdout.lower()
            if "not found" in lowered or "no such" in lowered:
                notes.append(
                    "pfd2png.sh appears unavailable in the configured image — "
                    "run `presto.validate_environment` and confirm with the "
                    "image maintainer."
                )
            else:
                notes.append("no .png/.ps produced; check stderr")
        return Pfd2PngResult(
            pfd_file=pfd_file, png_file=png, ps_file=ps, notes=notes
        )

    spec = RunSpec[Pfd2PngResult](
        tool_name="pfd2png",
        input_file=pfd_file,
        inputs_extra={"pfd_file": pfd_file},
        container_input_path="",
        presto_argv_builder=argv_builder,
        parser=parser,
        timeout_s=s.default_timeout_s,
        cpus=s.default_cpus,
        memory_mb=s.default_memory_mb,
        input_root="runs",
        container_workdir="/outputs/artifacts",
        pre_invocation_hook=_stage_pfd,
    )
    return execute(spec, s, backend, background=background)
