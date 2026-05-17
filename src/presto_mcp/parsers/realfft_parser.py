"""Parse PRESTO ``realfft`` output into a typed :class:`RealfftResult`.

realfft is nearly silent on stdout — the artifacts (``.fft``, copy of ``.inf``)
in ``run_dir/artifacts/`` are the truth source.
"""

from __future__ import annotations

import logging
from pathlib import Path

from ..errors import ParserError
from ..models import RealfftResult

log = logging.getLogger("presto_mcp.parsers.realfft")

_BOM = "﻿"


def parse(
    stdout: str,
    run_dir: Path | None = None,
    *,
    input_dat: str = "",
) -> RealfftResult:
    if not isinstance(stdout, str):
        raise ParserError(f"stdout must be str, got {type(stdout).__name__}")
    if stdout.startswith(_BOM):
        stdout = stdout[1:]
    # realfft can be near-silent; do NOT treat empty stdout as fatal.

    fft_file: str | None = None
    inf_file: str | None = None
    if run_dir is not None:
        artifacts_dir = run_dir / "artifacts"
        if artifacts_dir.is_dir():
            fft_hits = sorted(artifacts_dir.glob("*.fft"))
            inf_hits = sorted(artifacts_dir.glob("*.inf"))
            if fft_hits:
                fft_file = fft_hits[0].name
            if inf_hits:
                inf_file = inf_hits[0].name

    if fft_file is None and not stdout.strip():
        raise ParserError("realfft produced no .fft artifact and no stdout")

    return RealfftResult(input_dat=input_dat, fft_file=fft_file, inf_file=inf_file)
