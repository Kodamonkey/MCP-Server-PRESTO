"""Parse PRESTO ``accelsearch`` output into a typed :class:`AccelsearchResult`.

Top candidates come from the ``<prefix>_ACCEL_<zmax>.txtcand`` artifact PRESTO
writes (human-readable rows). Stdout is mostly progress / parameter echo.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from ..errors import ParserError
from ..models import AccelCandidate, AccelsearchResult

log = logging.getLogger("presto_mcp.parsers.accelsearch")

_BOM = "﻿"

_TXTCAND_ROW = re.compile(
    # cand  sigma  power  freq  fdot  z  ...  period  dm
    r"^\s*(\d+)\s+([\d.]+)\s+([\d.+\-eE]+)\s+([\d.+\-eE]+)\s+([\d.+\-eE]+)\s+([\d.+\-eE]+)"
)

_TOP_N = 20


def _parse_txtcand(txt: str, top_n: int) -> list[AccelCandidate]:
    out: list[AccelCandidate] = []
    for line in txt.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = _TXTCAND_ROW.match(line)
        if not m:
            continue
        try:
            cand_num = int(m.group(1))
            sigma = float(m.group(2))
            freq = float(m.group(4))
            z = float(m.group(6))
        except ValueError:
            continue
        period_ms = (1.0 / freq) * 1000.0 if freq != 0.0 else None
        out.append(
            AccelCandidate(
                cand_num=cand_num,
                sigma=sigma,
                frequency_hz=freq,
                period_ms=period_ms,
                z=z,
            )
        )
        if len(out) >= top_n:
            break
    return out


def parse(
    stdout: str,
    run_dir: Path | None = None,
    *,
    zmax: int = 0,
    numharm: int = 0,
    input_fft: str = "",
    wmax: int | None = None,
    sigma: float | None = None,
    ncpus: int | None = None,
    candidate_limit: int | None = None,
) -> AccelsearchResult:
    if not isinstance(stdout, str):
        raise ParserError(f"stdout must be str, got {type(stdout).__name__}")
    if stdout.startswith(_BOM):
        stdout = stdout[1:]

    top_n = candidate_limit if candidate_limit is not None else _TOP_N
    notes: list[str] = []
    cand_count: int | None = None
    accel_cand_file: str | None = None
    txtcand_file: str | None = None
    top_cands: list[AccelCandidate] = []

    if run_dir is not None:
        artifacts_dir = run_dir / "artifacts"
        if artifacts_dir.is_dir():
            cand_hits = sorted(artifacts_dir.glob("*ACCEL*[!t][!x][!t]"))
            cand_hits = [p for p in cand_hits if p.suffix not in {".cand", ".txtcand"}
                         and not p.name.endswith(".inf")]
            # canonical: file ending in _ACCEL_<zmax> (no .txtcand suffix)
            real_cands = [
                p for p in artifacts_dir.iterdir()
                if "_ACCEL_" in p.name and not p.name.endswith(".txtcand")
                and not p.name.endswith(".cand")
            ]
            if real_cands:
                accel_cand_file = sorted(real_cands)[0].name
            txt_hits = sorted(artifacts_dir.glob("*ACCEL*.txtcand"))
            if txt_hits:
                txtcand_file = txt_hits[0].name
                try:
                    txt = txt_hits[0].read_text(encoding="utf-8", errors="replace")
                    top_cands = _parse_txtcand(txt, top_n)
                    cand_count = sum(
                        1 for line in txt.splitlines()
                        if line.strip() and not line.lstrip().startswith("#")
                        and _TXTCAND_ROW.match(line)
                    )
                except OSError as e:
                    log.warning("failed to read txtcand %s: %s", txt_hits[0], e)

    if (
        candidate_limit is not None
        and cand_count is not None
        and cand_count > candidate_limit
    ):
        notes.append(
            f"top_candidates capped at candidate_limit={candidate_limit} "
            f"(cand_count={cand_count})"
        )

    return AccelsearchResult(
        zmax=int(zmax),
        numharm=int(numharm),
        input_fft=input_fft,
        wmax=wmax,
        sigma=sigma,
        ncpus=ncpus,
        accel_cand_file=accel_cand_file,
        accel_txtcand_file=txtcand_file,
        cand_count=cand_count,
        top_candidates=top_cands,
        notes=notes,
    )
