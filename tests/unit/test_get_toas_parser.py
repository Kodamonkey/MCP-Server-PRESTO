"""Unit tests for parsers.get_toas_parser."""

from __future__ import annotations

import pytest

from presto_mcp.errors import ParserError
from presto_mcp.parsers import get_toas_parser

_STDOUT = """\
Reading template 'sample.gaussians' ...
Loaded 4 Gaussian components.
Working on pfd file: prep.pfd
FORMAT 1
 prep.pfd  1564.250000  58849.123456789012345  0.10  gbt
 prep.pfd  1564.250000  58849.123456789012346  0.12  gbt
 prep.pfd  1564.250000  58849.123456789012347  0.11  gbt
Done.
"""


def test_parse_extracts_toa_lines() -> None:
    res = get_toas_parser.parse(
        _STDOUT, None,
        pfd_file="aaaa/artifacts/prep.pfd",
        template_file="sample.gaussians",
        num_subints=1, num_subbands=1,
    )
    assert res.pfd_file.endswith("prep.pfd")
    assert res.template_file == "sample.gaussians"
    assert res.num_toas == 3
    assert any("FORMAT 1" in line for line in res.toa_lines)
    assert any("58849.123456789012345" in line for line in res.toa_lines)


def test_parse_rejects_empty() -> None:
    with pytest.raises(ParserError, match="empty"):
        get_toas_parser.parse("", None)


def test_parse_rejects_no_toa_lines() -> None:
    with pytest.raises(ParserError, match="no TOA"):
        get_toas_parser.parse("Reading template ...\nDone\n", None)
