"""``presto.pfdzap`` — wrap ``pfdzap.py`` (experimental).

Applies simple time/frequency zapping commands to a ``.pfd``. Commands are
restricted to ``<low>:<high>`` tokens (validated by
``policies.check_pfdzap_commands``); arbitrary shell input is rejected. Marked
**experimental** because the script is not part of every PRESTO distribution.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from ..config import Settings, get_settings
from ..docker_backend import BackendProtocol
from ..errors import PathSecurityError, PolicyViolationError
from ..executor import RunSpec, execute
from ..models import PfdZapResult, ToolRunResult
from ..path_security import resolve_run_artifact
from ..policies import check_output_prefix, check_pfdzap_commands

log = logging.getLogger("presto_mcp.tools.pfdzap")

DEFAULT_PREFIX = "pfdzap"


def run_pfdzap(
    pfd_file: str,
    *,
    backend: BackendProtocol,
    zap_commands: list[str] | None = None,
    output_prefix: str | None = None,
    settings: Settings | None = None,
    background: bool = False,
) -> ToolRunResult[PfdZapResult]:
    """``pfdzap.py -o <prefix> <zap_file> <pfd>``.

    ``pfd_file`` is ``<run_id>/artifacts/<file>.pfd`` under ``RUNS_DIR``.
    ``zap_commands`` is an optional list of strict ``<low>:<high>`` tokens
    written into a sandboxed zaplist file under the new run's artifacts/.
    """
    s = settings or get_settings()
    cmds = check_pfdzap_commands(zap_commands)
    if cmds is None or not cmds:
        raise PolicyViolationError(
            "pfdzap requires at least one zap command of the form '<low>:<high>'"
        )
    prefix = check_output_prefix(output_prefix or DEFAULT_PREFIX)

    host_pfd = resolve_run_artifact(pfd_file, s.runs_dir)
    if host_pfd.suffix != ".pfd":
        raise PathSecurityError(f"pfdzap expects a .pfd file; got {host_pfd.name}")
    pfd_basename = host_pfd.name
    zap_filename = f"{prefix}.zap"

    def _stage(run_dir: Path, _extras: tuple[Path, ...]) -> None:
        artifacts_dir = run_dir / "artifacts"
        # Stage a copy of the source .pfd so we don't write into /runs (ro).
        shutil.copy(host_pfd, artifacts_dir / pfd_basename)
        # Write the sandboxed zap-commands file.
        (artifacts_dir / zap_filename).write_text(
            "\n".join(cmds) + "\n", encoding="utf-8"
        )

    def argv_builder(
        _container_input: str, _extras: tuple[str, ...], _run_dir: Path
    ) -> list[str]:
        return [
            "pfdzap.py",
            "-o", prefix,
            zap_filename,
            pfd_basename,
        ]

    def parser(stdout: str, run_dir: Path) -> PfdZapResult:
        artifacts_dir = run_dir / "artifacts"
        out_pfd: str | None = None
        notes: list[str] = []
        if artifacts_dir.is_dir():
            zapped = sorted(
                p.name
                for p in artifacts_dir.glob(f"{prefix}*.pfd")
                if p.name != pfd_basename
            )
            if zapped:
                out_pfd = zapped[0]
        if out_pfd is None:
            lowered = stdout.lower()
            if "not found" in lowered or "no such" in lowered:
                notes.append(
                    "pfdzap.py appears unavailable in the configured image — "
                    "run `presto.validate_environment`."
                )
            else:
                notes.append("no zapped .pfd produced; check stderr")
        return PfdZapResult(
            pfd_file=pfd_file,
            output_pfd_file=out_pfd,
            zap_commands_file=zap_filename,
            notes=notes,
        )

    spec = RunSpec[PfdZapResult](
        tool_name="pfdzap",
        input_file=None,
        inputs_extra={
            "pfd_file": pfd_file,
            "output_prefix": prefix,
            "zap_commands_count": str(len(cmds)),
        },
        container_input_path="",
        presto_argv_builder=argv_builder,
        parser=parser,
        timeout_s=s.default_timeout_s,
        cpus=s.default_cpus,
        memory_mb=s.default_memory_mb,
        container_workdir="/outputs/artifacts",
        pre_invocation_hook=_stage,
    )
    return execute(spec, s, backend, background=background)
