"""Parse PRESTO ``stacksearch.py`` output into a typed :class:`StackSearchResult`.

stacksearch.py is image-dependent and its exact output layout varies, so this
parser is deliberately defensive: it classifies the run's artifacts rather than
assuming a fixed schema, and never invents candidates.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from ..errors import ParserError
from ..models import StackSearchCandidate, StackSearchResult

log = logging.getLogger("presto_mcp.parsers.stacksearch")

_BOM = "﻿"
_TOP_N = 20

# A generic "candidate row": cand# sigma ... freq ...
_CAND_ROW = re.compile(
    r"^\s*(\d+)\s+([\d.]+)\s+[\d.+\-eE]+\s+([\d.+\-eE]+)"
)


def _parse_candidate_rows(text: str) -> list[StackSearchCandidate]:
    out: list[StackSearchCandidate] = []
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        m = _CAND_ROW.match(line)
        if not m:
            continue
        try:
            cand_num = int(m.group(1))
            sigma = float(m.group(2))
            freq = float(m.group(3))
        except ValueError:
            continue
        period_ms = (1.0 / freq) * 1000.0 if freq != 0.0 else None
        out.append(
            StackSearchCandidate(
                cand_num=cand_num,
                sigma=sigma,
                frequency_hz=freq,
                period_ms=period_ms,
            )
        )
        if len(out) >= _TOP_N:
            break
    return out


def parse(
    stdout: str,
    run_dir: Path | None = None,
    *,
    fft_files: tuple[str, ...] = (),
    staged_names: tuple[str, ...] = (),
) -> StackSearchResult:
    if not isinstance(stdout, str):
        raise ParserError(f"stdout must be str, got {type(stdout).__name__}")
    if stdout.startswith(_BOM):
        stdout = stdout[1:]

    candidate_files: list[str] = []
    summary_file: str | None = None
    top_candidates: list[StackSearchCandidate] = []
    notes: list[str] = []
    staged = set(staged_names)

    if run_dir is not None:
        artifacts_dir = run_dir / "artifacts"
        if artifacts_dir.is_dir():
            for p in sorted(artifacts_dir.iterdir()):
                if not p.is_file() or p.name in staged:
                    continue
                if p.suffix in {".fft", ".inf"}:
                    continue
                candidate_files.append(p.name)
                if summary_file is None and "sum" in p.name.lower():
                    summary_file = p.name
                if p.suffix in {".txtcand", ".cand", ".txt"} and not top_candidates:
                    try:
                        top_candidates = _parse_candidate_rows(
                            p.read_text(encoding="utf-8", errors="replace")
                        )
                    except OSError as e:
                        log.warning("failed to read %s: %s", p, e)

    if not candidate_files:
        notes.append("stacksearch produced no recognizable candidate artifacts")

    return StackSearchResult(
        fft_files=list(fft_files),
        candidate_files=candidate_files,
        summary_file=summary_file,
        top_candidates=top_candidates,
        notes=notes,
    )
