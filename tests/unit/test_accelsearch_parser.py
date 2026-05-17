"""Unit tests for parsers.accelsearch_parser."""

from __future__ import annotations

from pathlib import Path

import pytest

from presto_mcp.errors import ParserError
from presto_mcp.parsers import accelsearch_parser

_TXTCAND = """\
#  Cand   Sigma    Power     Freq      FFTReal   Z        Period(ms)   ...
   1      11.32    150.2     123.456   100.0     2.0      8.103
   2      8.45     90.1      55.555    50.0      -1.0     18.000
   3      7.10     60.0      999.999   30.0      0.5      1.000
"""


def test_parse_extracts_top_candidates(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "prep_ACCEL_200").write_bytes(b"X")
    (artifacts / "prep_ACCEL_200.txtcand").write_text(_TXTCAND)

    res = accelsearch_parser.parse(
        "ok\n", tmp_path, zmax=200, numharm=8, input_fft="prep.fft"
    )
    assert res.zmax == 200
    assert res.numharm == 8
    assert res.accel_txtcand_file == "prep_ACCEL_200.txtcand"
    assert res.accel_cand_file == "prep_ACCEL_200"
    assert len(res.top_candidates) == 3
    top = res.top_candidates[0]
    assert top.cand_num == 1
    assert top.sigma == 11.32
    assert top.frequency_hz == 123.456
    assert top.z == 2.0


def test_parse_no_artifacts_ok(tmp_path: Path) -> None:
    # accelsearch can complete with zero candidates.
    res = accelsearch_parser.parse(
        "no cands\n", tmp_path, zmax=200, numharm=8, input_fft="prep.fft"
    )
    assert res.cand_count is None
    assert res.top_candidates == []


def test_parse_rejects_non_string() -> None:
    with pytest.raises(ParserError, match="must be str"):
        accelsearch_parser.parse(42, None)  # type: ignore[arg-type]
