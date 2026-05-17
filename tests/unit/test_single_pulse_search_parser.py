"""Unit tests for parsers.single_pulse_search_parser."""

from __future__ import annotations

from pathlib import Path

from presto_mcp.parsers import single_pulse_search_parser

_SP_BODY = """\
# DM      Sigma      Time (s)     Sample    Downfact
  56.78   6.20       12.345        12345    2
  56.78   7.10       20.111        20111    4
  56.78   5.50       30.000        30000    1
"""


def test_parse_counts_pulses_and_max_snr(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "sub_DM56.78.singlepulse").write_text(_SP_BODY)
    (artifacts / "summary_singlepulse.ps").write_bytes(b"PS")

    res = single_pulse_search_parser.parse(
        "done\n", tmp_path,
        threshold=5.0, max_width_s=0.1,
        input_dat_files=("aaaa/artifacts/sub_DM56.78.dat",),
    )
    assert res.pulse_count == 3
    assert res.max_snr == 7.10
    assert res.singlepulse_files == ["sub_DM56.78.singlepulse"]
    assert res.ps_file == "summary_singlepulse.ps"


def test_parse_empty_run_dir_ok(tmp_path: Path) -> None:
    res = single_pulse_search_parser.parse(
        "", tmp_path, threshold=5.0, max_width_s=0.1
    )
    assert res.singlepulse_files == []
    assert res.pulse_count is None
