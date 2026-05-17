"""Parse PRESTO ``make_spd.py`` output into a typed :class:`MakeSpdResult`.

make_spd.py reads a ``groups.txt`` plus raw filterbank/PSRFITS plus
``*.singlepulse`` files and writes one ``.spd`` (numpy-saved) per candidate
into its working directory.
"""

from __future__ import annotations

import logging
from pathlib import Path

from ..errors import ParserError
from ..models import MakeSpdResult

log = logging.getLogger("presto_mcp.parsers.make_spd")

_BOM = "﻿"


def parse(
    stdout: str,
    run_dir: Path | None = None,
    *,
    raw_file: str = "",
    groups_file: str = "",
    input_singlepulse_files: tuple[str, ...] = (),
    mask_file: str | None = None,
) -> MakeSpdResult:
    if not isinstance(stdout, str):
        raise ParserError(f"stdout must be str, got {type(stdout).__name__}")
    if stdout.startswith(_BOM):
        stdout = stdout[1:]

    spd_files: list[str] = []
    if run_dir is not None:
        artifacts_dir = run_dir / "artifacts"
        if artifacts_dir.is_dir():
            spd_files = sorted(p.name for p in artifacts_dir.glob("*.spd"))

    return MakeSpdResult(
        raw_file=raw_file,
        groups_file=groups_file,
        input_singlepulse_files=list(input_singlepulse_files),
        mask_file=mask_file,
        spd_files=spd_files,
    )
