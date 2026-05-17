"""Parse PRESTO ``search_bin`` stdout into :class:`SearchBinResult`.

Best-effort parser: ``search_bin`` produces candidate file(s) and a textual
top-candidates table. The exact column layout differs across PRESTO versions;
we capture filenames + try to extract per-candidate fields when present.
"""

from __future__ import annotations

import contextlib
import logging
import re
from pathlib import Path

from ..errors import ParserError
from ..models import SearchBinCandidate, SearchBinResult

log = logging.getLogger("presto_mcp.parsers.search_bin")

_BOM = "﻿"

# Heuristic row pattern: "  1  freq=12.345 (P_ms=81.0) sigma=8.7 P_orb=12345.6"
_CAND_ROW = re.compile(
    r"^\s*(\d+)\s+(?:freq=)?(\d+\.\d+)\s*(?:\(P_ms=(\d+\.\d+)\))?"
    r"(?:\s+(?:sigma|sig)\s*=\s*(\d+\.\d+))?"
    r"(?:\s+(?:P_orb|Porb)\s*=\s*(\d+\.\d+))?",
    re.MULTILINE,
)


def parse(
    stdout: str,
    run_dir: Path | None = None,
    *,
    fft_file: str,
) -> SearchBinResult:
    if not isinstance(stdout, str):
        raise ParserError(f"stdout must be str, got {type(stdout).__name__}")
    if stdout.startswith(_BOM):
        stdout = stdout[1:]

    notes: list[str] = []
    cand_files: list[str] = []
    if run_dir is not None:
        artifacts_dir = run_dir / "artifacts"
        if artifacts_dir.is_dir():
            for pattern in ("*.cand", "*_cands*", "*bincand*"):
                cand_files.extend(p.name for p in sorted(artifacts_dir.glob(pattern)))
    if not cand_files:
        notes.append("no candidate files detected in artifacts/")

    candidates: list[SearchBinCandidate] = []
    for m in _CAND_ROW.finditer(stdout):
        with contextlib.suppress(ValueError):
            candidates.append(
                SearchBinCandidate(
                    cand_num=int(m.group(1)),
                    frequency_hz=float(m.group(2)),
                    period_ms=float(m.group(3)) if m.group(3) else None,
                    sigma=float(m.group(4)) if m.group(4) else None,
                    orb_p_s=float(m.group(5)) if m.group(5) else None,
                )
            )

    if not candidates and "Cand" not in stdout and "cand" not in stdout:
        notes.append("no top-candidates table recognized in stdout")

    return SearchBinResult(
        fft_file=fft_file,
        candidate_files=cand_files,
        top_candidates=candidates,
        notes=notes,
    )
