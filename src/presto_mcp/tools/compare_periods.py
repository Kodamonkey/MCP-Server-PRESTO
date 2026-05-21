"""``presto.compare_periods`` — cross-check a candidate period against ephemerides.

Utility tool (no Docker, no PRESTO execution): it reads ``.par`` files and
compares a candidate spin period against each pulsar's period and its
harmonics / subharmonics. This is the deterministic arithmetic behind a
"known-pulsar cross-check" — it never invents a detection, it only reports how
closely a candidate lines up with a catalogued ephemeris.
"""

from __future__ import annotations

import logging

from ..config import Settings, get_settings
from ..errors import PathSecurityError
from ..models import ComparePeriodsResult, PeriodMatch
from ..parsers import parfile_parser
from ..path_security import is_run_artifact_path, resolve_input_path, resolve_run_artifact
from ..policies import (
    check_compare_max_harmonic,
    check_compare_tolerance,
    check_par_file_count,
    check_period_ms,
)

log = logging.getLogger("presto_mcp.tools.compare_periods")


def _label(delta: float, tolerance: float) -> str:
    if delta <= tolerance * 0.01:
        return "exact"
    if delta <= tolerance * 0.1:
        return "near"
    return "weak"


def _best_match(
    cand_s: float, pulsar_s: float, max_harmonic: int
) -> tuple[int, float, float]:
    """Return (harmonic, predicted_period_s, relative_delta) for the best fit.

    harmonic n>0: candidate ≈ pulsar/n. n<0: candidate ≈ pulsar*|n|.
    """
    best_h = 1
    best_pred = pulsar_s
    best_delta = abs(cand_s - pulsar_s) / pulsar_s
    for n in range(1, max_harmonic + 1):
        # candidate is the n-th harmonic of the pulsar
        pred = pulsar_s / n
        delta = abs(cand_s - pred) / pred
        if delta < best_delta:
            best_h, best_pred, best_delta = n, pred, delta
        # candidate is the n-th subharmonic of the pulsar
        pred = pulsar_s * n
        delta = abs(cand_s - pred) / pred
        if delta < best_delta:
            best_h, best_pred, best_delta = -n, pred, delta
    return best_h, best_pred, best_delta


def run_compare_periods(
    period_ms: float,
    par_files: list[str],
    *,
    tolerance: float | None = None,
    max_harmonic: int | None = None,
    settings: Settings | None = None,
) -> ComparePeriodsResult:
    """Compare ``period_ms`` against each ``.par`` file's pulsar period."""
    s = settings or get_settings()
    cand_ms = check_period_ms(period_ms)
    tol = check_compare_tolerance(tolerance)
    max_h = check_compare_max_harmonic(max_harmonic)
    check_par_file_count(par_files)

    cand_s = cand_ms / 1000.0
    matches: list[PeriodMatch] = []
    notes: list[str] = []

    for rel in par_files:
        try:
            if is_run_artifact_path(rel):
                host = resolve_run_artifact(rel, s.runs_dir)
            else:
                host = resolve_input_path(rel, s.data_dir)
        except PathSecurityError as e:
            notes.append(f"{rel}: rejected ({e})")
            continue

        try:
            text = host.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            notes.append(f"{rel}: could not read ({e})")
            continue

        fields = parfile_parser.parse_par_text(text)
        pulsar_s = parfile_parser.spin_period_s(fields)
        name = parfile_parser.pulsar_name(fields)
        if pulsar_s is None:
            notes.append(f"{rel}: no P0/F0 found; cannot compare")
            continue

        harmonic, pred_s, delta = _best_match(cand_s, pulsar_s, max_h)
        if delta <= tol:
            matches.append(
                PeriodMatch(
                    par_file=rel,
                    pulsar_name=name,
                    candidate_period_ms=cand_ms,
                    matched_period_ms=pred_s * 1000.0,
                    harmonic=harmonic,
                    delta=delta,
                    confidence_label=_label(delta, tol),  # type: ignore[arg-type]
                )
            )

    summary = (
        f"{len(matches)} of {len(par_files)} par file(s) match candidate "
        f"period {cand_ms:.6g} ms within tolerance {tol:g} "
        f"(harmonics up to {max_h})."
    )
    if not matches:
        notes.append("no ephemeris matched — candidate is not a known pulsar")

    return ComparePeriodsResult(
        period_ms=cand_ms,
        par_files=list(par_files),
        tolerance=tol,
        max_harmonic=max_h,
        matches=matches,
        summary=summary,
        notes=notes,
    )


__all__ = ["run_compare_periods"]
