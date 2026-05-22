"""Parse candidates from raw PRESTO outputs into normalized :class:`Candidate`.

Sources covered:

  * ``*.singlepulse`` / ``*.singlepulse.gz`` — single_pulse_search events.
  * ``*_ACCEL_<zmax>`` text tables + ``*.txtcand`` — accelsearch candidates.
  * ``*.bestprof`` — prepfold folded candidates.
  * ``groups.txt`` / ``*.groups`` — rrattrap RRAT groups.
  * ``cands.txt`` — ACCEL_sift surviving candidates.

Rules: include **every** parseable candidate (not only the best ones); never
invent a scientific parameter — unknown fields stay ``None``. A single
unparseable file yields a warning, never an exception that aborts the run.
"""

from __future__ import annotations

import csv
import gzip
import io
import json
import logging
import re
from collections.abc import Iterable
from pathlib import Path

from .schemas import Candidate, CandidateType

log = logging.getLogger("presto_mcp.reporting.candidate_parser")

# Near-zero DM single pulses are almost always terrestrial interference.
_RFI_DM_CEILING = 2.0
_SP_CANDIDATE_SIGMA = 7.0


def parse_candidates(roots: Iterable[Path]) -> tuple[list[Candidate], list[str]]:
    """Scan ``roots`` recursively and return ``(candidates, warnings)``.

    ``roots`` is typically one or more ``runs/<run_id>/`` directories. All
    candidates from all sources are preserved; ids and ranks are assigned at
    the end so they are stable across a deterministic scan order.
    """
    warnings: list[str] = []
    cands: list[Candidate] = []
    seen: set[Path] = set()

    files: list[Path] = []
    for root in roots:
        root = Path(root)
        if not root.exists():
            warnings.append(f"workdir does not exist: {root}")
            continue
        if root.is_file():
            files.append(root)
            continue
        files.extend(p for p in sorted(root.rglob("*")) if p.is_file())

    for path in sorted(set(files)):
        if path in seen:
            continue
        seen.add(path)
        try:
            parsed = _dispatch(path)
        except Exception as e:  # noqa: BLE001 - one bad file must not abort the scan
            warnings.append(f"failed to parse {path.name}: {type(e).__name__}: {e}")
            log.warning("candidate parse failed for %s", path, exc_info=True)
            continue
        cands.extend(parsed)

    _assign_ids_and_ranks(cands)
    return cands, warnings


def _dispatch(path: Path) -> list[Candidate]:
    name = path.name.lower()
    if name.endswith(".singlepulse.gz"):
        return _parse_singlepulse(path, gzipped=True)
    if name.endswith(".singlepulse"):
        return _parse_singlepulse(path, gzipped=False)
    if name.endswith(".bestprof"):
        return _parse_bestprof(path)
    if name == "groups.txt" or name.endswith(".groups") or "groups" in name and name.endswith(".txt"):
        return _parse_rrat_groups(path)
    if name == "cands.txt":
        return _parse_sift_candstxt(path)
    if "_accel_" in name and (path.suffix == "" or name.endswith(".txtcand")):
        return _parse_accel_table(path)
    return []


# -- single pulse --------------------------------------------------------------


def _parse_singlepulse(path: Path, *, gzipped: bool) -> list[Candidate]:
    if gzipped:
        with gzip.open(path, "rt", encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
    else:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()

    out: list[Candidate] = []
    for line in lines:
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        parts = s.split()
        if len(parts) < 5:
            continue
        try:
            dm = float(parts[0])
            sigma = float(parts[1])
            t = float(parts[2])
            sample = int(float(parts[3]))
            downfact = int(float(parts[4]))
        except ValueError:
            continue
        is_rfi = dm < _RFI_DM_CEILING
        out.append(
            Candidate(
                candidate_id="pending",
                candidate_type=CandidateType.SINGLE_PULSE,
                source_stage="single_pulse_search",
                source_file=path.name,
                dm=dm,
                snr_or_sigma=sigma,
                time_sec=t,
                sample=sample,
                downfact=downfact,
                width_bins=downfact,
                is_rfi_like=is_rfi,
                classification_hint=_singlepulse_hint(dm, sigma),
            )
        )
    return out


def _singlepulse_hint(dm: float, sigma: float) -> str:
    if dm < _RFI_DM_CEILING:
        return "likely RFI/noise (near-zero DM)"
    if sigma >= _SP_CANDIDATE_SIGMA:
        return "single-pulse candidate — requires human inspection"
    return "low-significance single-pulse event"


# -- accelsearch ---------------------------------------------------------------

_DASH_RE = re.compile(r"^-{5,}")


def _parse_accel_table(path: Path) -> list[Candidate]:
    """Best-effort parse of a PRESTO ``_ACCEL_<zmax>`` candidate table.

    The table starts after a dashed separator; each row begins with an integer
    candidate number followed by sigma. Period (ms) and frequency (Hz) carry
    parenthesized uncertainties (``156.3500(12)``) which are stripped.
    """
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    out: list[Candidate] = []
    in_table = False
    for line in lines:
        s = line.strip()
        if _DASH_RE.match(s):
            in_table = True
            continue
        if not in_table:
            continue
        if not s:
            break  # table ends at first blank line
        parts = s.split()
        if len(parts) < 2:
            continue
        cand_tok = parts[0].rstrip(".")
        if not cand_tok.isdigit():
            continue
        try:
            cand_num = int(cand_tok)
            sigma = float(parts[1])
        except ValueError:
            continue
        period_ms = _clean_number(parts[5]) if len(parts) > 5 else None
        freq_hz = _clean_number(parts[6]) if len(parts) > 6 else None
        out.append(
            Candidate(
                candidate_id="pending",
                candidate_type=CandidateType.ACCELERATION,
                source_stage="accelsearch",
                source_file=path.name,
                snr_or_sigma=sigma,
                period_sec=(period_ms / 1000.0) if period_ms is not None else None,
                frequency_hz=freq_hz,
                classification_hint="acceleration-search candidate — requires human inspection",
                raw_metadata={"cand_num": str(cand_num)},
            )
        )
    return out


# -- prepfold ------------------------------------------------------------------


def _parse_bestprof(path: Path) -> list[Candidate]:
    text = path.read_text(encoding="utf-8", errors="replace")
    fields: dict[str, str] = {}
    for line in text.splitlines():
        ls = line.lstrip()
        if not ls.startswith("#") or "=" not in ls:
            continue
        key, _, value = ls.lstrip("#").partition("=")
        fields[key.strip()] = value.strip()

    dm = _to_float(fields.get("Best DM"))
    period_ms = _to_float(_first_token(fields.get("P_topo (ms)")))
    chi2 = _to_float(_first_token(fields.get("Reduced chi-sqr")))
    raw = {k: v for k, v in fields.items() if v}
    return [
        Candidate(
            candidate_id="pending",
            candidate_type=CandidateType.FOLDED,
            source_stage="prepfold",
            source_file=path.name,
            dm=dm,
            period_sec=(period_ms / 1000.0) if period_ms is not None else None,
            frequency_hz=(1000.0 / period_ms) if period_ms else None,
            folded=True,
            snr_or_sigma=chi2,
            classification_hint="folded candidate — requires human inspection",
            raw_metadata=raw,
        )
    ]


# -- rrattrap ------------------------------------------------------------------


def _parse_rrat_groups(path: Path) -> list[Candidate]:
    """Tolerant parser for rrattrap ``groups.txt`` (format varies by version)."""
    text = path.read_text(encoding="utf-8", errors="replace")
    blocks = re.split(r"\n\s*\n", text)
    out: list[Candidate] = []
    for block in blocks:
        if not block.strip():
            continue
        dm = _grep_float(block, r"(?:centre|center|mean)\s*dm[^\d-]*([-\d.]+)")
        if dm is None:
            lo = _grep_float(block, r"min\s*dm[^\d-]*([-\d.]+)")
            hi = _grep_float(block, r"max\s*dm[^\d-]*([-\d.]+)")
            if lo is not None and hi is not None:
                dm = (lo + hi) / 2.0
        sigma = _grep_float(block, r"(?:max\s*sigma|highest\s*snr|max\s*snr)[^\d-]*([-\d.]+)")
        rank = _grep_int(block, r"rank[^\d-]*(\d+)")
        npulses = _grep_int(block, r"(?:number of pulses|n(?:um)?\s*pulses)[^\d]*(\d+)")
        if dm is None and sigma is None and rank is None:
            continue
        raw: dict[str, str] = {}
        if npulses is not None:
            raw["num_pulses"] = str(npulses)
        out.append(
            Candidate(
                candidate_id="pending",
                candidate_type=CandidateType.RRAT_GROUP,
                source_stage="rrattrap",
                source_file=path.name,
                dm=dm,
                snr_or_sigma=sigma,
                rank=rank,
                classification_hint="RRAT-like group — requires human inspection",
                raw_metadata=raw,
            )
        )
    return out


# -- ACCEL_sift ----------------------------------------------------------------


def _parse_sift_candstxt(path: Path) -> list[Candidate]:
    """Light parser for an ACCEL_sift ``cands.txt`` summary (whitespace rows)."""
    out: list[Candidate] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        parts = s.split()
        floats = [_to_float(p) for p in parts]
        numeric = [f for f in floats if f is not None]
        if len(numeric) < 2:
            continue
        # cands.txt rows commonly carry a DM and a sigma among the numeric cols.
        dm = next((f for f in numeric if 0.0 <= f <= 10000.0), None)
        sigma = next((f for f in reversed(numeric) if 0.0 < f < 1000.0), None)
        out.append(
            Candidate(
                candidate_id="pending",
                candidate_type=CandidateType.PERIODIC,
                source_stage="sifting",
                source_file=path.name,
                dm=dm,
                snr_or_sigma=sigma,
                classification_hint="sifted periodic candidate — requires human inspection",
                raw_metadata={"row": s[:200]},
            )
        )
    return out


# -- finalization --------------------------------------------------------------

_ID_PREFIX: dict[CandidateType, str] = {
    CandidateType.SINGLE_PULSE: "sp",
    CandidateType.ACCELERATION: "acc",
    CandidateType.PERIODIC: "per",
    CandidateType.FOLDED: "fold",
    CandidateType.RRAT_GROUP: "rrat",
    CandidateType.UNKNOWN: "cand",
}


def _assign_ids_and_ranks(cands: list[Candidate]) -> None:
    """Assign stable per-type ids and a global rank by significance (desc)."""
    counters: dict[CandidateType, int] = {}
    for c in cands:
        n = counters.get(c.candidate_type, 0) + 1
        counters[c.candidate_type] = n
        c.candidate_id = f"{_ID_PREFIX.get(c.candidate_type, 'cand')}-{n:04d}"

    ranked = sorted(
        cands,
        key=lambda c: (c.snr_or_sigma is None, -(c.snr_or_sigma or 0.0)),
    )
    for i, c in enumerate(ranked, start=1):
        c.rank = i


# -- numeric helpers -----------------------------------------------------------


def _to_float(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value.strip())
    except (ValueError, AttributeError):
        return None


def _first_token(value: str | None) -> str | None:
    if value is None:
        return None
    parts = value.split()
    return parts[0] if parts else None


def _clean_number(token: str) -> float | None:
    """Strip a parenthesized uncertainty (``156.3500(12)``) and parse a float."""
    cleaned = re.sub(r"\(.*?\)", "", token).strip()
    return _to_float(cleaned)


def _grep_float(text: str, pattern: str) -> float | None:
    m = re.search(pattern, text, re.IGNORECASE)
    return _to_float(m.group(1)) if m else None


def _grep_int(text: str, pattern: str) -> int | None:
    m = re.search(pattern, text, re.IGNORECASE)
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


# -- CSV export ----------------------------------------------------------------

CSV_COLUMNS: tuple[str, ...] = (
    "run_id",
    "input_file",
    "candidate_id",
    "candidate_type",
    "source_stage",
    "source_file",
    "dm",
    "snr_or_sigma",
    "time_sec",
    "sample",
    "period_sec",
    "frequency_hz",
    "acceleration_or_z",
    "width_bins",
    "downfact",
    "rank",
    "folded",
    "classification_hint",
    "is_known_pulsar_candidate",
    "is_frb_like",
    "is_rfi_like",
    "visual_artifact_path",
    "waterfall_png_path",
    "waterfall_pdf_path",
    "raw_metadata_json",
    "notes",
)


def _cell(value: object) -> str:
    """Render one CSV cell — empty string for ``None`` (never invent)."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def candidates_to_csv(
    candidates: Iterable[Candidate],
    *,
    run_id: str,
    input_file: str | None,
) -> str:
    """Render candidates as a normalized ``candidates.csv`` document.

    With no candidates the result is a header-only CSV (still valid output
    when the user explicitly asked for a candidate export).
    """
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(CSV_COLUMNS)
    for c in candidates:
        writer.writerow(
            [
                _cell(run_id),
                _cell(input_file),
                _cell(c.candidate_id),
                _cell(c.candidate_type.value),
                _cell(c.source_stage),
                _cell(c.source_file),
                _cell(c.dm),
                _cell(c.snr_or_sigma),
                _cell(c.time_sec),
                _cell(c.sample),
                _cell(c.period_sec),
                _cell(c.frequency_hz),
                _cell(c.acceleration_or_z),
                _cell(c.width_bins),
                _cell(c.downfact),
                _cell(c.rank),
                _cell(c.folded),
                _cell(c.classification_hint),
                _cell(c.is_known_pulsar_candidate),
                _cell(c.is_frb_like),
                _cell(c.is_rfi_like),
                _cell(c.paths.visual_artifact_path),
                _cell(c.paths.waterfall_png_path),
                _cell(c.paths.waterfall_pdf_path),
                json.dumps(c.raw_metadata, ensure_ascii=True, separators=(",", ":")),
                _cell(c.notes),
            ]
        )
    return buf.getvalue()


__all__ = ["CSV_COLUMNS", "candidates_to_csv", "parse_candidates"]
