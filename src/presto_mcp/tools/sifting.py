"""``presto.sifting`` — wrap PRESTO's ``ACCEL_sift.py`` over many ``.accel`` files.

ACCEL_sift.py scans a working directory for ``*ACCEL_*`` candidate files,
loads their companion ``.inf`` headers, and prints a deduplicated
"surviving candidates" table.

We stage every input ``.accel`` (plus sibling ``.inf`` and ``.cand`` if
present) into ``run_dir/staging/`` and invoke ACCEL_sift.py from there.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from ..config import Settings, get_settings
from ..docker_backend import BackendProtocol
from ..errors import PathSecurityError
from ..executor import RunSpec, execute
from ..models import SiftingResult, ToolRunResult
from ..parsers import sifting_parser
from ..path_security import resolve_run_artifact
from ..policies import (
    check_sift_accel_count,
    check_sift_low_dm_cutoff,
    check_sift_min_num_dms,
    check_sift_sigma,
)

log = logging.getLogger("presto_mcp.tools.sifting")


def run_sifting(
    accel_files: list[str],
    *,
    backend: BackendProtocol,
    min_num_dms: int = 2,
    low_dm_cutoff: float = 2.0,
    sigma_threshold: float = 4.0,
    settings: Settings | None = None,
    background: bool = False,
) -> ToolRunResult[SiftingResult]:
    """``cd /outputs/staging && ACCEL_sift.py`` (invoked via ``-w`` flag)."""
    s = settings or get_settings()
    check_sift_accel_count(len(accel_files))
    md = check_sift_min_num_dms(min_num_dms)
    lo = check_sift_low_dm_cutoff(low_dm_cutoff)
    sig = check_sift_sigma(sigma_threshold)

    host_paths: list[Path] = []
    for rel in accel_files:
        host = resolve_run_artifact(rel, s.runs_dir)
        if "ACCEL" not in host.name:
            raise PathSecurityError(
                f"sifting expects ACCEL_* files; got {host.name}"
            )
        host_paths.append(host)

    seen: set[str] = set()
    for h in host_paths:
        if h.name in seen:
            raise PathSecurityError(
                f"duplicate filename in sifting inputs after staging: {h.name}"
            )
        seen.add(h.name)

    def hook(run_dir: Path, _extras: tuple[Path, ...]) -> None:
        staging = run_dir / "staging"
        staging.mkdir(parents=True, exist_ok=True)
        for host in host_paths:
            shutil.copy2(host, staging / host.name)
            # Companion files share the basename up to ``_ACCEL_*``; copy any
            # sibling ``.inf`` / ``.cand`` for ACCEL_sift to find.
            base = host.name.split("_ACCEL_")[0]
            src_dir = host.parent
            for sibling in src_dir.glob(f"{base}*"):
                if sibling.is_file() and sibling != host:
                    target = staging / sibling.name
                    if not target.exists():
                        shutil.copy2(sibling, target)

    def argv_builder(
        _container_input: str, _extras: tuple[str, ...], _run_dir: Path
    ) -> list[str]:
        # ACCEL_sift.py reads its current working directory; -w sets it.
        return [
            "ACCEL_sift.py",
            "--minDMs", str(md),
            "--lowDM", str(lo),
            "--sigma", str(sig),
            "--workdir", "/outputs/staging",
        ]

    def parser(stdout: str, run_dir: Path) -> SiftingResult:
        return sifting_parser.parse(
            stdout,
            run_dir,
            min_num_dms=md,
            low_dm_cutoff=lo,
            sigma_threshold=sig,
            input_accel_files=tuple(accel_files),
        )

    spec = RunSpec[SiftingResult](
        tool_name="sifting",
        input_file=None,
        inputs_extra={
            "min_num_dms": str(md),
            "low_dm_cutoff": str(lo),
            "sigma_threshold": str(sig),
            "accel_count": str(len(accel_files)),
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
