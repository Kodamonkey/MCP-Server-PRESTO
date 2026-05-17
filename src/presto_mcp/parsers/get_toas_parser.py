"""Parse PRESTO ``get_TOAs.py`` stdout into :class:`GetTOAsResult`.

get_TOAs prints TEMPO/TEMPO2 TOA lines (one per measurement) on stdout.
The TEMPO2 form begins with an ``@`` header line; the legacy TEMPO1 form
prints whitespace-separated columns. We capture all non-empty,
non-comment lines that don't begin with the human-readable banner words.
"""

from __future__ import annotations

import logging
from pathlib import Path

from ..errors import ParserError
from ..models import GetTOAsResult

log = logging.getLogger("presto_mcp.parsers.get_toas")

_BOM = "﻿"

# Words that prefix human-readable status lines we should drop.
_BANNER_PREFIXES = (
    "Reading",
    "Writing",
    "Loaded",
    "Using",
    "Template",
    "Working",
    "Computed",
    "Found",
    "Done",
    "Telescope",
)


def parse(
    stdout: str,
    _run_dir: Path | None = None,
    *,
    pfd_file: str = "",
    template_file: str = "",
    num_subints: int = 0,
    num_subbands: int = 0,
) -> GetTOAsResult:
    if not isinstance(stdout, str):
        raise ParserError(f"stdout must be str, got {type(stdout).__name__}")
    if stdout.startswith(_BOM):
        stdout = stdout[1:]
    if not stdout.strip():
        raise ParserError("get_TOAs stdout is empty")

    toa_lines: list[str] = []
    for raw in stdout.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        if line.lstrip().startswith(("#", "C ", "C\t")):
            continue
        if line.lstrip().startswith(_BANNER_PREFIXES):
            continue
        # FORMAT 1 header in TEMPO2 mode
        if line.strip() == "FORMAT 1":
            toa_lines.append(line)
            continue
        # crude heuristic: TOA lines have at least 3 columns and contain a digit
        parts = line.split()
        if len(parts) >= 3 and any(any(ch.isdigit() for ch in p) for p in parts):
            toa_lines.append(line)

    if not toa_lines:
        raise ParserError("get_TOAs stdout contained no TOA-like lines")

    # If FORMAT 1 header present, exclude from the TOA count.
    num_toas = sum(1 for line in toa_lines if line.strip() != "FORMAT 1")

    return GetTOAsResult(
        pfd_file=pfd_file,
        template_file=template_file,
        num_subints=int(num_subints),
        num_subbands=int(num_subbands),
        num_toas=num_toas,
        toa_lines=toa_lines,
    )
