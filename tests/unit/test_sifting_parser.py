"""Unit tests for parsers.sifting_parser."""

from __future__ import annotations

import pytest

from presto_mcp.errors import ParserError
from presto_mcp.parsers import sifting_parser

_STDOUT = """\
Reading candidates...
Total candidates read: 1234
Sifting candidates...
# DM       Sigma     Period(ms)   Freq(Hz)    Hits
  56.78    11.32     8.103        123.456     3
  78.90    8.45      18.000       55.555      2
  20.00    7.10      1.000        999.999     2

Surviving candidates: 3
Done.
"""


def test_parse_survivors_and_totals() -> None:
    res = sifting_parser.parse(
        _STDOUT, None,
        min_num_dms=2, low_dm_cutoff=2.0, sigma_threshold=4.0,
        input_accel_files=("a", "b"),
    )
    assert res.total_input_cands == 1234
    assert res.total_surviving == 3
    assert len(res.surviving_candidates) == 3
    first = res.surviving_candidates[0]
    assert first.dm == 56.78
    assert first.sigma == 11.32
    assert first.period_ms == 8.103
    assert first.num_hits == 3


def test_parse_rejects_empty() -> None:
    with pytest.raises(ParserError, match="empty"):
        sifting_parser.parse("", None)
