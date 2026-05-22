"""Unit tests for the reporting candidate parser + CSV writer."""

from __future__ import annotations

import gzip
from pathlib import Path

from presto_mcp.reporting.candidate_parser import (
    CSV_COLUMNS,
    candidates_to_csv,
    parse_candidates,
)
from presto_mcp.reporting.schemas import CandidateType

_SP = (
    "# DM      Sigma     Time (s)    Sample    Downfact\n"
    "5.00      8.20      12.345      123456    2\n"
    "0.50      6.10      3.200       9000      1\n"
)


def test_parses_singlepulse(tmp_path: Path) -> None:
    (tmp_path / "obs.singlepulse").write_text(_SP, encoding="utf-8")
    cands, warnings = parse_candidates([tmp_path])
    assert len(cands) == 2
    assert all(c.candidate_type == CandidateType.SINGLE_PULSE for c in cands)
    first = cands[0]
    assert first.dm == 5.0
    assert first.snr_or_sigma == 8.2
    assert first.time_sec == 12.345
    assert first.sample == 123456
    assert first.downfact == 2
    assert warnings == []


def test_parses_singlepulse_gz(tmp_path: Path) -> None:
    with gzip.open(tmp_path / "obs.singlepulse.gz", "wt", encoding="utf-8") as fh:
        fh.write(_SP)
    cands, _ = parse_candidates([tmp_path])
    assert len(cands) == 2
    assert cands[0].candidate_type == CandidateType.SINGLE_PULSE


def test_zero_candidates(tmp_path: Path) -> None:
    (tmp_path / "empty.singlepulse").write_text(
        "# DM Sigma Time Sample Downfact\n", encoding="utf-8"
    )
    cands, warnings = parse_candidates([tmp_path])
    assert cands == []
    assert warnings == []


def test_does_not_invent_missing_fields(tmp_path: Path) -> None:
    (tmp_path / "obs.singlepulse").write_text(_SP, encoding="utf-8")
    cands, _ = parse_candidates([tmp_path])
    # single-pulse rows carry no period / acceleration — must stay None.
    assert all(c.period_sec is None for c in cands)
    assert all(c.acceleration_or_z is None for c in cands)
    assert all(c.frequency_hz is None for c in cands)


def test_preserves_all_candidates(tmp_path: Path) -> None:
    rows = "\n".join(f"{10 + i}.0 {5 + i}.0 {i}.0 {1000 + i} 1" for i in range(40))
    (tmp_path / "many.singlepulse").write_text(
        "# DM Sigma Time Sample Downfact\n" + rows + "\n", encoding="utf-8"
    )
    cands, _ = parse_candidates([tmp_path])
    assert len(cands) == 40  # all kept, not only the best


def test_parses_bestprof(tmp_path: Path) -> None:
    (tmp_path / "cand.bestprof").write_text(
        "# Best DM        =  57.000\n# P_topo (ms)    =  156.350  +/- 0.01\n",
        encoding="utf-8",
    )
    cands, _ = parse_candidates([tmp_path])
    folded = [c for c in cands if c.candidate_type == CandidateType.FOLDED]
    assert len(folded) == 1
    assert folded[0].dm == 57.0
    assert folded[0].period_sec is not None
    assert abs(folded[0].period_sec - 0.15635) < 1e-6
    assert folded[0].folded is True


def test_csv_header_only_when_empty() -> None:
    text = candidates_to_csv([], run_id="20260101T000000Z-ABC234", input_file=None)
    lines = text.splitlines()
    assert len(lines) == 1
    assert lines[0].split(",") == list(CSV_COLUMNS)


def test_csv_rows(tmp_path: Path) -> None:
    (tmp_path / "obs.singlepulse").write_text(_SP, encoding="utf-8")
    cands, _ = parse_candidates([tmp_path])
    text = candidates_to_csv(cands, run_id="20260101T000000Z-ABC234", input_file="obs.fil")
    lines = text.splitlines()
    assert len(lines) == 3  # header + 2 candidates
    assert lines[1].startswith("20260101T000000Z-ABC234,obs.fil,")
