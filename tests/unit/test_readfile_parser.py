"""readfile parser contract test against committed real-PRESTO stdout."""

from __future__ import annotations

from pathlib import Path

import pytest

from presto_mcp.errors import ParserError
from presto_mcp.parsers import readfile_parser


def test_parses_real_fixture(stdout_fixture_dir: Path) -> None:
    text = (stdout_fixture_dir / "readfile_J0532+3305.txt").read_text(encoding="utf-8-sig")
    m = readfile_parser.parse(text)
    assert m.file_format == "SIGPROC filterbank"
    assert m.source_name == "J0532+3305"
    assert m.telescope == "Fake"
    assert m.num_channels == 672
    assert m.central_freq_mhz == pytest.approx(1564.25)
    assert m.sample_time_us == pytest.approx(256.0)
    assert m.low_channel_mhz == pytest.approx(1396.5)
    assert m.high_channel_mhz == pytest.approx(1732.0)
    assert m.channel_width_mhz == pytest.approx(0.5)
    assert m.total_bandwidth_mhz == pytest.approx(336.0)
    assert m.duration_s == pytest.approx(60.0)
    assert m.bits_per_sample == 8
    assert m.mjd_start == pytest.approx(57762.15474537036789)
    assert m.ra == "05:31:58.0000"
    assert m.dec == "33:08:04.0000"
    assert "Beam FWHM (deg)" in m.raw_fields  # unmapped key preserved


def test_parses_minimal_synthetic() -> None:
    text = """\
Assuming the data is a SIGPROC filterbank file.

         Number of channels = 8
         Central freq (MHz) = 100.5
                Source Name = TEST
"""
    m = readfile_parser.parse(text)
    assert m.file_format == "SIGPROC filterbank"
    assert m.num_channels == 8
    assert m.central_freq_mhz == 100.5
    assert m.source_name == "TEST"


def test_detects_psrfits_format() -> None:
    text = "PSRFITS Header summary follows:\nKey = value\n"
    m = readfile_parser.parse(text)
    assert m.file_format == "PSRFITS"


def test_empty_stdout_rejected() -> None:
    with pytest.raises(ParserError, match="empty"):
        readfile_parser.parse("")


def test_no_kv_pairs_rejected() -> None:
    with pytest.raises(ParserError, match="no 'key = value' pairs"):
        readfile_parser.parse("blah\nblah\nblah\n")


def test_bad_cast_doesnt_kill_parse() -> None:
    """A bad value for one numeric key falls through to raw_fields only."""
    text = "Source Name = TEST\nNumber of channels = NOT_AN_INT\n"
    m = readfile_parser.parse(text)
    assert m.source_name == "TEST"
    assert m.num_channels is None
    assert m.raw_fields["Number of channels"] == "NOT_AN_INT"


def test_bom_tolerated() -> None:
    text = "﻿" + "Source Name = X\n"
    m = readfile_parser.parse(text)
    assert m.source_name == "X"
