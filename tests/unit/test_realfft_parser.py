"""Unit tests for parsers.realfft_parser."""

from __future__ import annotations

from pathlib import Path

import pytest

from presto_mcp.errors import ParserError
from presto_mcp.parsers import realfft_parser


def test_parse_globs_fft_and_inf(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "prep.fft").write_bytes(b"F")
    (artifacts / "prep.inf").write_bytes(b"i")

    res = realfft_parser.parse("", tmp_path, input_dat="prep.dat")
    assert res.input_dat == "prep.dat"
    assert res.fft_file == "prep.fft"
    assert res.inf_file == "prep.inf"


def test_parse_rejects_when_no_artifact_and_no_stdout() -> None:
    with pytest.raises(ParserError, match="no .fft"):
        realfft_parser.parse("", None)


def test_parse_accepts_stdout_only() -> None:
    # No run_dir; non-empty stdout means realfft ran but no artifact discovery possible.
    res = realfft_parser.parse("some banner text\n", None, input_dat="x.dat")
    assert res.input_dat == "x.dat"
    assert res.fft_file is None
