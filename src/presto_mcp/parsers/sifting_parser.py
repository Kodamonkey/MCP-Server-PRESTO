"""Parse PRESTO ``ACCEL_sift.py`` stdout into :class:`SiftingResult`.

ACCEL_sift prints a "Sifting candidates..." header, then a table of
surviving candidates. The exact layout has shifted across PRESTO releases;
we accept any row starting with a non-comment whitespace-separated tuple of
``DM   sigma   period_ms   freq_hz   hits`` and stash the raw line in ``note``.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from ..errors import ParserError
from ..models import SiftCandidate, SiftingResult

log = logging.getLogger("presto_mcp.parsers.sifting")

_BOM = "﻿"

_TOTAL_INPUT_RE = re.compile(r"Total candidates.*?:\s*(\d+)", re.IGNORECASE)
_TOTAL_SURV_RE = re.compile(r"(?:Surviving|Kept|Remaining)\s+candidates.*?:\s*(\d+)", re.IGNORECASE)


def _try_parse_row(line: str) -> SiftCandidate | None:
    parts = line.split()
    if len(parts) < 4:
        return None
    # heuristic: at least 4 numeric tokens
    try:
        nums = [float(p) for p in parts[:5]]
    except ValueError:
        return None
    # Map first 5 by heuristic order: DM, sigma, period_ms, freq_hz, hits.
    cand = SiftCandidate(
        dm=nums[0] if len(nums) > 0 else None,
        sigma=nums[1] if len(nums) > 1 else None,
        period_ms=nums[2] if len(nums) > 2 else None,
        frequency_hz=nums[3] if len(nums) > 3 else None,
        num_hits=int(nums[4]) if len(nums) > 4 and nums[4].is_integer() else None,
        note=line.strip(),
    )
    return cand


def parse(
    stdout: str,
    run_dir: Path | None = None,
    *,
    min_num_dms: int = 0,
    low_dm_cutoff: float = 0.0,
    sigma_threshold: float = 0.0,
    input_accel_files: tuple[str, ...] = (),
) -> SiftingResult:
    if not isinstance(stdout, str):
        raise ParserError(f"stdout must be str, got {type(stdout).__name__}")
    if stdout.startswith(_BOM):
        stdout = stdout[1:]
    if not stdout.strip():
        raise ParserError("sifting stdout is empty")

    total_input: int | None = None
    total_surv: int | None = None
    if (m := _TOTAL_INPUT_RE.search(stdout)) is not None:
        total_input = int(m.group(1))
    if (m := _TOTAL_SURV_RE.search(stdout)) is not None:
        total_surv = int(m.group(1))

    survivors: list[SiftCandidate] = []
    in_table = False
    for line in stdout.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        # Try to detect transition into the candidate table heuristically: lines
        # starting with a float followed by another float.
        cand = _try_parse_row(stripped)
        if cand is not None:
            survivors.append(cand)
            in_table = True
        elif in_table:
            # leaving the table
            break

    summary_file: str | None = None
    if run_dir is not None:
        artifacts_dir = run_dir / "artifacts"
        if artifacts_dir.is_dir():
            hits = sorted(artifacts_dir.glob("*siftcands*"))
            if hits:
                summary_file = hits[0].name

    return SiftingResult(
        input_accel_files=list(input_accel_files),
        min_num_dms=int(min_num_dms),
        low_dm_cutoff=float(low_dm_cutoff),
        sigma_threshold=float(sigma_threshold),
        surviving_candidates=survivors,
        total_input_cands=total_input,
        total_surviving=total_surv if total_surv is not None else len(survivors) or None,
        summary_file=summary_file,
    )
