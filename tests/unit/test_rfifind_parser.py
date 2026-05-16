"""rfifind parser contract test against committed real-PRESTO stdout."""

from __future__ import annotations

from pathlib import Path

import pytest

from presto_mcp.errors import ParserError
from presto_mcp.parsers import rfifind_parser


def test_parses_real_fixture(stdout_fixture_dir: Path) -> None:
    text = (stdout_fixture_dir / "rfifind_J0532+3305.txt").read_text(encoding="utf-8-sig")
    summary = rfifind_parser.parse(text, run_dir=None, time_s=2.0)
    assert summary.time_s == 2.0
    assert summary.num_channels == 672
    assert summary.sample_time == pytest.approx(0.000256)
    assert summary.num_intervals == 22176
    assert summary.good_intervals == 17019
    assert summary.bad_intervals == 4485
    assert summary.rfi_instances == 1323
    # 100 - 76.745 ≈ 23.255
    assert summary.pct_masked == pytest.approx(23.255, abs=0.01)
    # From the "Writing ..." lines.
    assert summary.mask_file == "rfi_rfifind.mask"
    assert summary.rfi_file == "rfi_rfifind.rfi"
    assert summary.stats_file == "rfi_rfifind.stats"


def test_artifacts_resolved_from_run_dir(stdout_fixture_dir: Path, tmp_path: Path) -> None:
    text = (stdout_fixture_dir / "rfifind_J0532+3305.txt").read_text(encoding="utf-8-sig")
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    for name in ("foo.mask", "foo.rfi", "foo.stats", "foo.ps"):
        (artifacts / name).write_bytes(b"\x00")

    summary = rfifind_parser.parse(text, run_dir=tmp_path, time_s=2.0)
    # On-disk wins over stdout strings.
    assert summary.mask_file == "foo.mask"
    assert summary.rfi_file == "foo.rfi"
    assert summary.stats_file == "foo.stats"
    assert summary.ps_file == "foo.ps"


def test_empty_rejected() -> None:
    with pytest.raises(ParserError, match="empty"):
        rfifind_parser.parse("   \n  \n", time_s=2.0)


def test_minimal_synthetic_recovers_what_it_can() -> None:
    text = """\
Pulsar Data RFI Finder
    Num of channels = 4
    Sample time (s) = 0.001
Total number of intervals in the data:  100
There are 7 RFI instances.
Number of  good  intervals:     80 ( 80.000%)
Number of  bad   intervals:     15 ( 15.000%)
Writing mask data  to '/outputs/foo.mask'.
Writing  RFI data  to '/outputs/foo.rfi'.
Writing statistics to '/outputs/foo.stats'.
"""
    s = rfifind_parser.parse(text, time_s=1.0)
    assert s.num_channels == 4
    assert s.sample_time == pytest.approx(0.001)
    assert s.num_intervals == 100
    assert s.good_intervals == 80
    assert s.bad_intervals == 15
    assert s.rfi_instances == 7
    assert s.pct_masked == pytest.approx(20.0)
    assert s.mask_file == "foo.mask"
