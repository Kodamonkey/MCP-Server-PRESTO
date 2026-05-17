"""``presto.makezaplist`` — wrap ``makezaplist.py``.

Generate a zaplist from a ``.birds`` file under ``DATA_DIR``. Marked
**experimental** until syntax is verified against the configured image.
"""

from __future__ import annotations

import logging
from pathlib import Path

from ..config import Settings, get_settings
from ..docker_backend import BackendProtocol
from ..executor import RunSpec, execute
from ..models import MakeZaplistResult, ToolRunResult

log = logging.getLogger("presto_mcp.tools.makezaplist")


def run_makezaplist(
    input_file: str,
    *,
    backend: BackendProtocol,
    settings: Settings | None = None,
    background: bool = False,
) -> ToolRunResult[MakeZaplistResult]:
    """``makezaplist.py <input_file>`` → produces ``<basename>.zaplist``.

    ``input_file`` (typically ``.birds``) under ``DATA_DIR``. Run inside the
    artifacts dir so the output lands there.
    """
    s = settings or get_settings()

    def argv_builder(
        container_input: str, _extras: tuple[str, ...], _run_dir: Path
    ) -> list[str]:
        return ["makezaplist.py", container_input]

    def parser(_stdout: str, run_dir: Path) -> MakeZaplistResult:
        artifacts_dir = run_dir / "artifacts"
        zap: str | None = None
        notes: list[str] = []
        if artifacts_dir.is_dir():
            hits = sorted(p.name for p in artifacts_dir.glob("*.zaplist"))
            if hits:
                zap = hits[0]
        if zap is None:
            notes.append("no .zaplist produced; check stderr / verify input is .birds")
        return MakeZaplistResult(
            input_file=input_file, zaplist_file=zap, notes=notes
        )

    spec = RunSpec[MakeZaplistResult](
        tool_name="makezaplist",
        input_file=input_file,
        inputs_extra={},
        container_input_path="",
        presto_argv_builder=argv_builder,
        parser=parser,
        timeout_s=s.default_timeout_s,
        cpus=s.default_cpus,
        memory_mb=s.default_memory_mb,
        container_workdir="/outputs/artifacts",
    )
    return execute(spec, s, backend, background=background)
