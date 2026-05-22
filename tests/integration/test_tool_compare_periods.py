"""Tests for the presto.compare_periods utility tool (no Docker)."""

from __future__ import annotations

from pathlib import Path

import pytest

from presto_mcp.config import Settings
from presto_mcp.tools.compare_periods import run_compare_periods

# P0 = 1/30 s -> 33.3333... ms
_PAR_CRAB = "PSRJ J0534+2200\nF0 30.0\nDM 56.7\n"
_PAR_NO_PERIOD = "PSRJ J9999+9999\nDM 12.0\nRAJ 00:00:00\n"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    data = tmp_path / "data"
    data.mkdir()
    (data / "crab.par").write_text(_PAR_CRAB, encoding="utf-8")
    (data / "noperiod.par").write_text(_PAR_NO_PERIOD, encoding="utf-8")
    return Settings(
        image="alex88ridolfi/presto5:png",
        data_dir=data.resolve(),
        runs_dir=(tmp_path / "runs").resolve(),
        outputs_dir=(tmp_path / "outputs").resolve(),
        default_cpus=2.0, default_memory_mb=1024, default_timeout_s=60,
        network="none", skip_healthcheck=True,
    )


def test_fundamental_match(settings: Settings) -> None:
    res = run_compare_periods(33.33333, ["crab.par"], settings=settings)
    assert len(res.matches) == 1
    m = res.matches[0]
    assert m.pulsar_name == "J0534+2200"
    assert m.harmonic == 1
    assert m.confidence_label in {"exact", "near"}


def test_harmonic_match(settings: Settings) -> None:
    # candidate at half the period -> candidate is the 2nd harmonic
    res = run_compare_periods(16.66667, ["crab.par"], settings=settings)
    assert len(res.matches) == 1
    assert res.matches[0].harmonic == 2


def test_subharmonic_match(settings: Settings) -> None:
    # candidate at twice the period -> 2nd subharmonic
    res = run_compare_periods(66.66667, ["crab.par"], settings=settings)
    assert len(res.matches) == 1
    assert res.matches[0].harmonic == -2


def test_no_match(settings: Settings) -> None:
    res = run_compare_periods(5.0, ["crab.par"], settings=settings)
    assert res.matches == []
    assert any("not a known pulsar" in n for n in res.notes)


def test_par_without_period_is_noted(settings: Settings) -> None:
    res = run_compare_periods(33.33333, ["noperiod.par"], settings=settings)
    assert res.matches == []
    assert any("no P0/F0" in n for n in res.notes)


def test_absolute_path_rejected_as_note(settings: Settings) -> None:
    res = run_compare_periods(33.33333, ["/etc/passwd"], settings=settings)
    assert res.matches == []
    assert any("rejected" in n for n in res.notes)
