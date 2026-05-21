"""Tests for the presto.binary_info utility tool (no Docker)."""

from __future__ import annotations

from pathlib import Path

import pytest

from presto_mcp.config import Settings
from presto_mcp.tools.binary_info import run_binary_info

_PAR_BINARY = (
    "PSRJ J0737-3039A\n"
    "F0 44.054069\n"
    "DM 48.92\n"
    "BINARY DD\n"
    "PB 0.10225156248\n"
    "A1 1.415032\n"
    "ECC 0.0877775\n"
    "OM 87.0331\n"
    "T0 55700.0\n"
)
_PAR_ISOLATED = "PSRJ J0534+2200\nF0 30.0\nDM 56.7\n"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    data = tmp_path / "data"
    data.mkdir()
    (data / "binary.par").write_text(_PAR_BINARY, encoding="utf-8")
    (data / "isolated.par").write_text(_PAR_ISOLATED, encoding="utf-8")
    return Settings(
        image="alex88ridolfi/presto5:png",
        data_dir=data.resolve(),
        runs_dir=(tmp_path / "runs").resolve(),
        outputs_dir=(tmp_path / "outputs").resolve(),
        logs_dir=(tmp_path / "logs").resolve(),
        default_cpus=2.0, default_memory_mb=1024, default_timeout_s=60,
        network="none", skip_healthcheck=True,
    )


def test_binary_summary(settings: Settings) -> None:
    res = run_binary_info("binary.par", settings=settings)
    assert res.is_binary is True
    assert res.pulsar_name == "J0737-3039A"
    summary = res.binary_summary
    assert summary["binary_model"] == "DD"
    assert summary["orbital_period_s"] is not None
    # PB 0.10225 d -> ~8834 s
    assert 8000.0 < float(summary["orbital_period_s"]) < 9500.0  # type: ignore[arg-type]
    k = summary["radial_velocity_amplitude_km_s"]
    assert k is not None and float(k) > 0.0
    assert summary["observed_period_max_ms"] is not None


def test_isolated_pulsar(settings: Settings) -> None:
    res = run_binary_info("isolated.par", settings=settings)
    assert res.is_binary is False
    assert any("isolated" in n for n in res.notes)


def test_make_plot_not_supported_is_noted(settings: Settings) -> None:
    res = run_binary_info("binary.par", make_plot=True, settings=settings)
    assert any("make_plot is not supported" in n for n in res.notes)
    assert res.plot_files == []
