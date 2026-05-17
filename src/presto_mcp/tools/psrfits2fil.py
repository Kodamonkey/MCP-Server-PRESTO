"""``presto.psrfits2fil`` — wrap ``psrfits2fil.py``.

Convert PSRFITS search-format to SIGPROC ``.fil``. Input under ``DATA_DIR``;
outputs land in ``runs/<run_id>/artifacts/``.
"""

from __future__ import annotations

import logging
from pathlib import Path

from ..config import Settings, get_settings
from ..docker_backend import BackendProtocol
from ..executor import RunSpec, execute
from ..models import Psrfits2FilResult, ToolRunResult
from ..policies import check_output_prefix

log = logging.getLogger("presto_mcp.tools.psrfits2fil")

DEFAULT_PREFIX = "fil"


def run_psrfits2fil(
    input_file: str,
    *,
    backend: BackendProtocol,
    output_prefix: str | None = None,
    settings: Settings | None = None,
    background: bool = False,
) -> ToolRunResult[Psrfits2FilResult]:
    """``psrfits2fil.py -o <prefix> <input>`` → produces ``<prefix>.fil``."""
    s = settings or get_settings()
    prefix = check_output_prefix(output_prefix or DEFAULT_PREFIX)

    def argv_builder(
        container_input: str, _extras: tuple[str, ...], _run_dir: Path
    ) -> list[str]:
        return [
            "psrfits2fil.py",
            "-o",
            f"/outputs/artifacts/{prefix}",
            container_input,
        ]

    def parser(_stdout: str, run_dir: Path) -> Psrfits2FilResult:
        artifacts_dir = run_dir / "artifacts"
        fils: list[str] = []
        infs: list[str] = []
        notes: list[str] = []
        if artifacts_dir.is_dir():
            fils = sorted(p.name for p in artifacts_dir.glob("*.fil"))
            infs = sorted(p.name for p in artifacts_dir.glob("*.inf"))
        if not fils:
            notes.append("no .fil produced; check stderr for psrfits2fil.py errors")
        return Psrfits2FilResult(
            input_file=input_file,
            output_prefix=prefix,
            fil_files=fils,
            inf_files=infs,
            notes=notes,
        )

    spec = RunSpec[Psrfits2FilResult](
        tool_name="psrfits2fil",
        input_file=input_file,
        inputs_extra={"output_prefix": prefix},
        container_input_path="",
        presto_argv_builder=argv_builder,
        parser=parser,
        timeout_s=s.default_timeout_s,
        cpus=s.default_cpus,
        memory_mb=s.default_memory_mb,
    )
    return execute(spec, s, backend, background=background)
