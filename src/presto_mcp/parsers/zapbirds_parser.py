"""Parse PRESTO ``zapbirds`` output into a typed :class:`ZapbirdsResult`.

zapbirds rewrites the input ``.fft`` in place (a backup ``.fft.zap_bak`` may
appear depending on flags). stdout typically reports ``Read N frequencies to
zap from the zaplist`` plus per-zap log lines.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from ..errors import ParserError
from ..models import ZapbirdsResult

log = logging.getLogger("presto_mcp.parsers.zapbirds")

_BOM = "﻿"
_NUM_ZAPS_RE = re.compile(
    r"(?:Read|Zapping)\s+(\d+)\s+(?:frequencies|birds|bird)", re.IGNORECASE
)


def parse(
    stdout: str,
    run_dir: Path | None = None,
    *,
    input_fft: str = "",
    zaplist_file: str = "",
) -> ZapbirdsResult:
    if not isinstance(stdout, str):
        raise ParserError(f"stdout must be str, got {type(stdout).__name__}")
    if stdout.startswith(_BOM):
        stdout = stdout[1:]

    num_zaps: int | None = None
    for line in stdout.splitlines():
        m = _NUM_ZAPS_RE.search(line)
        if m:
            try:
                num_zaps = int(m.group(1))
                break
            except ValueError:
                continue

    zapped_fft: str | None = None
    inf_file: str | None = None
    if run_dir is not None:
        artifacts_dir = run_dir / "artifacts"
        if artifacts_dir.is_dir():
            fft_hits = sorted(artifacts_dir.glob("*.fft"))
            if fft_hits:
                zapped_fft = fft_hits[0].name
            inf_hits = sorted(artifacts_dir.glob("*.inf"))
            if inf_hits:
                inf_file = inf_hits[0].name

    if zapped_fft is None and not stdout.strip():
        raise ParserError("zapbirds produced no .fft artifact and no stdout")

    return ZapbirdsResult(
        input_fft=input_fft,
        zaplist_file=zaplist_file,
        zapped_fft=zapped_fft,
        inf_file=inf_file,
        num_zaps=num_zaps,
    )
