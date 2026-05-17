"""Parse PRESTO ``prepsubband`` stdout into a typed :class:`PrepsubbandResult`.

prepsubband emits one ``<prefix>_DM<dm>.dat`` (and ``.inf``) per DM trial.
Filenames come from the on-disk run-dir glob; the stdout text is too verbose
to parse reliably.
"""

from __future__ import annotations

import logging
from pathlib import Path

from ..errors import ParserError
from ..models import PrepsubbandResult

log = logging.getLogger("presto_mcp.parsers.prepsubband")

_BOM = "﻿"


def parse(
    stdout: str,
    run_dir: Path | None = None,
    *,
    dm_low: float = 0.0,
    dm_step: float = 0.0,
    num_dms: int = 0,
    num_subbands: int = 0,
    output_prefix: str = "",
) -> PrepsubbandResult:
    if not isinstance(stdout, str):
        raise ParserError(f"stdout must be str, got {type(stdout).__name__}")
    if stdout.startswith(_BOM):
        stdout = stdout[1:]
    if not stdout.strip():
        raise ParserError("prepsubband stdout is empty")

    dat_files: list[str] = []
    inf_files: list[str] = []
    if run_dir is not None:
        artifacts_dir = run_dir / "artifacts"
        if artifacts_dir.is_dir():
            dat_files = sorted(p.name for p in artifacts_dir.glob("*.dat"))
            inf_files = sorted(p.name for p in artifacts_dir.glob("*.inf"))

    return PrepsubbandResult(
        dm_low=float(dm_low),
        dm_step=float(dm_step),
        num_dms=int(num_dms),
        num_subbands=int(num_subbands),
        output_prefix=output_prefix,
        dat_files=dat_files,
        inf_files=inf_files,
    )
