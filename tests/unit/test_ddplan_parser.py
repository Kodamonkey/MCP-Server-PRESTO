"""Unit tests for parsers.ddplan_parser."""

from __future__ import annotations

import pytest

from presto_mcp.errors import ParserError
from presto_mcp.parsers import ddplan_parser

_STDOUT = """\
DDplan results for 1564.250 MHz, 336.000 MHz BW, 672 channels

  Low DM    High DM   dDM     DownSamp   dsubDM   #DMs   WorkFract
  --------  --------  ------  ---------  -------  -----  ---------
  0.000     30.000    0.10    1          4.00     300    0.5
  30.000    100.000   0.20    2          8.00     350    0.5

Total work fraction: 1.0
"""


def test_parse_table_rows() -> None:
    res = ddplan_parser.parse(
        _STDOUT,
        None,
        dm_low=0.0,
        dm_high=100.0,
        freq_mhz=1564.25,
        bw_mhz=336.0,
        num_channels=672,
        sample_time_us=64.0,
    )
    assert len(res.passes) == 2
    assert res.passes[0].low_dm == 0.0
    assert res.passes[0].dm_step == 0.1
    assert res.passes[0].downsamp == 1
    assert res.passes[0].dms_per_call == 300
    assert res.passes[1].low_dm == 30.0
    assert res.passes[1].dms_per_call == 350
    assert res.num_dms == 650
    assert res.freq_mhz == 1564.25
    assert res.num_channels == 672


def test_parse_rejects_empty() -> None:
    with pytest.raises(ParserError, match="empty"):
        ddplan_parser.parse("", None)


def test_parse_rejects_no_rows() -> None:
    with pytest.raises(ParserError, match="no recognizable"):
        ddplan_parser.parse("blah blah\nno rows here\n", None)
