"""``presto.downsample_filterbank`` — wrap ``downsample_filterbank.py``.

Produces a downsampled ``.fil`` for fast debugging / lighter analysis. Input
under ``DATA_DIR``; output under ``runs/<run_id>/artifacts/``.
"""

from __future__ import annotations

import logging
from pathlib import Path

from ..config import Settings, get_settings
from ..docker_backend import BackendProtocol
from ..executor import RunSpec, execute
from ..models import DownsampleFilterbankResult, ToolRunResult
from ..policies import check_downsample_factor

log = logging.getLogger("presto_mcp.tools.downsample_filterbank")


def run_downsample_filterbank(
    input_file: str,
    *,
    backend: BackendProtocol,
    factor: int,
    settings: Settings | None = None,
    background: bool = False,
) -> ToolRunResult[DownsampleFilterbankResult]:
    """``downsample_filterbank.py <factor> <input>``.

    PRESTO writes ``<basename>_DSn.fil`` next to the input by default. We run
    inside the artifacts dir as workdir so the output lands there.
    """
    s = settings or get_settings()
    f = check_downsample_factor(factor)

    def argv_builder(
        container_input: str, _extras: tuple[str, ...], _run_dir: Path
    ) -> list[str]:
        return ["downsample_filterbank.py", str(f), container_input]

    def parser(_stdout: str, run_dir: Path) -> DownsampleFilterbankResult:
        artifacts_dir = run_dir / "artifacts"
        out_file: str | None = None
        notes: list[str] = []
        if artifacts_dir.is_dir():
            fils = sorted(p.name for p in artifacts_dir.glob("*.fil"))
            if fils:
                out_file = fils[0]
        if out_file is None:
            notes.append(
                "no .fil under artifacts/; downsample_filterbank.py may have "
                "written next to the input (read-only data/) — verify image behavior"
            )
        return DownsampleFilterbankResult(
            input_file=input_file,
            factor=f,
            output_file=out_file,
            notes=notes,
        )

    spec = RunSpec[DownsampleFilterbankResult](
        tool_name="downsample_filterbank",
        input_file=input_file,
        inputs_extra={"factor": str(f)},
        container_input_path="",
        presto_argv_builder=argv_builder,
        parser=parser,
        timeout_s=s.default_timeout_s,
        cpus=s.default_cpus,
        memory_mb=s.default_memory_mb,
        container_workdir="/outputs/artifacts",
    )
    return execute(spec, s, backend, background=background)
