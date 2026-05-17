"""Unit tests for parsers.prepsubband_parser."""

from __future__ import annotations

from pathlib import Path

import pytest

from presto_mcp.errors import ParserError
from presto_mcp.parsers import prepsubband_parser

_STDOUT = "Working on DM = 0.00\nWorking on DM = 0.10\nDone.\n"


def test_parse_globs_artifacts(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    for dm in ("0.00", "0.10", "0.20"):
        (artifacts / f"sub_DM{dm}.dat").write_bytes(b"d")
        (artifacts / f"sub_DM{dm}.inf").write_bytes(b"i")

    res = prepsubband_parser.parse(
        _STDOUT, tmp_path,
        dm_low=0.0, dm_step=0.1, num_dms=3, num_subbands=32, output_prefix="sub",
    )
    assert res.output_prefix == "sub"
    assert res.num_dms == 3
    assert len(res.dat_files) == 3
    assert len(res.inf_files) == 3
    assert "sub_DM0.00.dat" in res.dat_files


def test_parse_rejects_empty() -> None:
    with pytest.raises(ParserError, match="empty"):
        prepsubband_parser.parse("", None)
