"""Integration test for presto.fourier_fold (experimental)."""

from __future__ import annotations

from pathlib import Path

import pytest

from presto_mcp.config import Settings
from presto_mcp.errors import PolicyViolationError
from presto_mcp.models import RunStatus
from presto_mcp.tools.fourier_fold import run_fourier_fold
from tests.fakes.fake_docker_backend import FakeDockerBackend, FakeResponse

PRIOR_RUN_ID = "20260517T120000Z-EEEEEE"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    data = tmp_path / "data"
    data.mkdir()
    runs = tmp_path / "runs"
    prior = runs / PRIOR_RUN_ID / "artifacts"
    prior.mkdir(parents=True)
    (prior / "obs.fft").write_bytes(b"f" * 32)
    return Settings(
        image="alex88ridolfi/presto5:png",
        data_dir=data.resolve(),
        runs_dir=runs.resolve(),
        outputs_dir=(tmp_path / "outputs").resolve(),
        logs_dir=(tmp_path / "logs").resolve(),
        default_cpus=2.0, default_memory_mb=1024, default_timeout_s=60,
        network="none", skip_healthcheck=True,
    )


def test_fourier_fold_with_period(settings: Settings) -> None:
    backend = FakeDockerBackend(
        responses={
            "fourier_fold.py": FakeResponse(
                stdout="ok\n",
                status=RunStatus.SUCCESS,
                artifacts={"obs.prof": b"profile", "obs.png": b"\x89PNG"},
            )
        }
    )
    result = run_fourier_fold(
        f"{PRIOR_RUN_ID}/artifacts/obs.fft",
        backend=backend,
        period_seconds=0.0337,
        dm=56.7,
        settings=settings,
    )
    assert result.status == RunStatus.SUCCESS
    assert result.result is not None
    assert result.result.profile_file == "obs.prof"
    assert result.result.plot_file == "obs.png"
    assert result.result.summary is not None
    assert result.result.summary.period_s == pytest.approx(0.0337)
    assert result.result.summary.dm == pytest.approx(56.7)

    argv = backend.calls[0].invocation.argv
    assert "fourier_fold.py" in argv
    assert "-p" in argv and "0.0337" in argv
    assert "-dm" in argv and "56.7" in argv
    assert f"/runs/{PRIOR_RUN_ID}/artifacts/obs.fft" in argv


def test_fourier_fold_requires_exactly_one_of_period_or_freq(
    settings: Settings,
) -> None:
    backend = FakeDockerBackend()
    with pytest.raises(PolicyViolationError):
        run_fourier_fold(
            f"{PRIOR_RUN_ID}/artifacts/obs.fft",
            backend=backend,
            settings=settings,
        )
    with pytest.raises(PolicyViolationError):
        run_fourier_fold(
            f"{PRIOR_RUN_ID}/artifacts/obs.fft",
            backend=backend,
            period_seconds=0.1,
            frequency_hz=10.0,
            settings=settings,
        )
    assert backend.calls == []
