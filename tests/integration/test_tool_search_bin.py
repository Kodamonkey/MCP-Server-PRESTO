"""Integration test for presto.search_bin (advanced)."""

from __future__ import annotations

from pathlib import Path

import pytest

from presto_mcp.config import Settings
from presto_mcp.errors import PolicyViolationError
from presto_mcp.models import RunStatus
from presto_mcp.tools.search_bin import run_search_bin
from tests.fakes.fake_docker_backend import FakeDockerBackend, FakeResponse

PRIOR_RUN_ID = "20260517T120000Z-GGGGGG"


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
        default_cpus=2.0, default_memory_mb=1024, default_timeout_s=60,
        network="none", skip_healthcheck=True,
    )


def test_search_bin_with_band(settings: Settings) -> None:
    backend = FakeDockerBackend(
        responses={
            "search_bin": FakeResponse(
                stdout="ran\n",
                status=RunStatus.SUCCESS,
                artifacts={"obs.cand": b"cand"},
            )
        }
    )
    result = run_search_bin(
        f"{PRIOR_RUN_ID}/artifacts/obs.fft",
        backend=backend,
        low_hz=1.0,
        high_hz=1000.0,
        settings=settings,
    )
    assert result.status == RunStatus.SUCCESS
    assert result.result is not None
    assert "obs.cand" in result.result.candidate_files

    argv = backend.calls[0].invocation.argv
    assert "search_bin" in argv
    assert "-flo" in argv and "1.0" in argv
    assert "-fhi" in argv and "1000.0" in argv
    assert f"/runs/{PRIOR_RUN_ID}/artifacts/obs.fft" in argv


def test_search_bin_rejects_bad_band(settings: Settings) -> None:
    backend = FakeDockerBackend()
    with pytest.raises(PolicyViolationError):
        run_search_bin(
            f"{PRIOR_RUN_ID}/artifacts/obs.fft",
            backend=backend,
            low_hz=10.0,
            high_hz=5.0,
            settings=settings,
        )
    with pytest.raises(PolicyViolationError):
        run_search_bin(
            f"{PRIOR_RUN_ID}/artifacts/obs.fft",
            backend=backend,
            low_hz=1.0,
            settings=settings,
        )
    assert backend.calls == []
