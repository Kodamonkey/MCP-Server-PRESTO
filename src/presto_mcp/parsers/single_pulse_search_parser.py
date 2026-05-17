"""Parse PRESTO ``single_pulse_search.py`` output into a typed
:class:`SinglePulseSearchResult`.

Each input ``X.dat`` produces ``X.singlepulse`` with one row per detection
(``DM   sigma   time   sample   downfact``). A summary ``.ps`` plot is
written if multiple inputs are given.
"""

from __future__ import annotations

import logging
from pathlib import Path

from ..errors import ParserError
from ..models import SinglePulseSearchResult

log = logging.getLogger("presto_mcp.parsers.single_pulse_search")

_BOM = "﻿"


def _count_pulses_and_max_snr(sp_files: list[Path]) -> tuple[int, float | None]:
    total = 0
    max_snr: float | None = None
    for f in sp_files:
        try:
            for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
                if not line.strip() or line.lstrip().startswith("#"):
                    continue
                parts = line.split()
                if len(parts) < 5:
                    continue
                total += 1
                try:
                    sigma = float(parts[1])
                except ValueError:
                    continue
                if max_snr is None or sigma > max_snr:
                    max_snr = sigma
        except OSError as e:
            log.warning("failed to read singlepulse file %s: %s", f, e)
    return total, max_snr


def parse(
    stdout: str,
    run_dir: Path | None = None,
    *,
    threshold: float = 0.0,
    max_width_s: float = 0.0,
    input_dat_files: tuple[str, ...] = (),
) -> SinglePulseSearchResult:
    if not isinstance(stdout, str):
        raise ParserError(f"stdout must be str, got {type(stdout).__name__}")
    if stdout.startswith(_BOM):
        stdout = stdout[1:]
    # single_pulse_search.py can be terse; do not insist on non-empty stdout.

    sp_files: list[str] = []
    ps_file: str | None = None
    pulse_count: int | None = None
    max_snr: float | None = None

    if run_dir is not None:
        artifacts_dir = run_dir / "artifacts"
        if artifacts_dir.is_dir():
            sp_paths = sorted(artifacts_dir.glob("*.singlepulse"))
            sp_files = [p.name for p in sp_paths]
            ps_hits = sorted(artifacts_dir.glob("*singlepulse*.ps"))
            if ps_hits:
                ps_file = ps_hits[0].name
            else:
                # generic fallback
                ps_any = sorted(artifacts_dir.glob("*.ps"))
                if ps_any:
                    ps_file = ps_any[0].name
            if sp_paths:
                pulse_count, max_snr = _count_pulses_and_max_snr(sp_paths)

    return SinglePulseSearchResult(
        threshold=float(threshold),
        max_width_s=float(max_width_s),
        input_dat_files=list(input_dat_files),
        singlepulse_files=sp_files,
        ps_file=ps_file,
        pulse_count=pulse_count,
        max_snr=max_snr,
    )
