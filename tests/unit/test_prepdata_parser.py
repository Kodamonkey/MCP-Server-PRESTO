"""Unit tests for parsers.prepdata_parser."""

from __future__ import annotations

from pathlib import Path

import pytest

from presto_mcp.errors import ParserError
from presto_mcp.parsers import prepdata_parser

_STDOUT = """Reading from file 'sample.fil' ...
Total points (N) :  4194304
Sample dt (s)    :  6.4e-05
Writing 'prep.dat' ...
Done.
"""


def test_parse_extracts_fields_and_artifacts(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "prep.dat").write_bytes(b"d")
    (artifacts / "prep.inf").write_bytes(b"i")

    res = prepdata_parser.parse(_STDOUT, tmp_path, dm=56.78, output_prefix="prep")
    assert res.dm == 56.78
    assert res.output_prefix == "prep"
    assert res.num_samples == 4194304
    assert res.sample_time_s == 6.4e-05
    assert res.dat_file == "prep.dat"
    assert res.inf_file == "prep.inf"


def test_parse_rejects_empty() -> None:
    with pytest.raises(ParserError, match="empty"):
        prepdata_parser.parse("", None)


def test_parse_handles_bom(tmp_path: Path) -> None:
    res = prepdata_parser.parse("﻿" + _STDOUT, tmp_path, dm=1.0, output_prefix="p")
    assert res.num_samples == 4194304


def test_parse_rejects_non_string() -> None:
    with pytest.raises(ParserError, match="must be str"):
        prepdata_parser.parse(42, None)  # type: ignore[arg-type]
