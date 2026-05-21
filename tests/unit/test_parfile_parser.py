"""Unit tests for the minimal .par ephemeris parser."""

from __future__ import annotations

from presto_mcp.parsers import parfile_parser as pp


def test_parse_basic_fields() -> None:
    text = "PSRJ J0534+2200\nF0 29.946923 1 0.00001\nDM 56.77\n"
    fields = pp.parse_par_text(text)
    assert fields["PSRJ"] == "J0534+2200"
    assert fields["F0"] == "29.946923"
    assert pp.pulsar_name(fields) == "J0534+2200"


def test_spin_period_from_f0_and_p0() -> None:
    assert pp.spin_period_s(pp.parse_par_text("F0 50.0\n")) == 0.02
    assert pp.spin_period_s(pp.parse_par_text("P0 0.5\n")) == 0.5


def test_comment_lines_ignored() -> None:
    fields = pp.parse_par_text("# a comment\nC tempo comment\nF0 10.0\n")
    assert "F0" in fields and len(fields) == 1


def test_fortran_d_exponent() -> None:
    assert pp.as_float("1.5D-3") == 0.0015


def test_binary_detection_and_orbital_period() -> None:
    fields = pp.parse_par_text("BINARY DD\nPB 1.5\nA1 2.0\n")
    assert pp.is_binary(fields) is True
    assert pp.orbital_period_s(fields) == 1.5 * 86_400.0


def test_eccentricity_from_ell1_eps() -> None:
    fields = pp.parse_par_text("BINARY ELL1\nEPS1 0.003\nEPS2 0.004\n")
    e = pp.eccentricity(fields)
    assert e is not None
    assert abs(e - 0.005) < 1e-9
