"""Integration test for presto.weights_to_ignorechan (experimental)."""

from __future__ import annotations

from pathlib import Path

import pytest

from presto_mcp.config import Settings
from presto_mcp.errors import PolicyViolationError
from presto_mcp.models import RunStatus
from presto_mcp.tools.weights_to_ignorechan import run_weights_to_ignorechan
from tests.fakes.fake_docker_backend import FakeDockerBackend, FakeResponse

PRIOR_RUN_ID = "20260517T120000Z-DDDDDD"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    data = tmp_path / "data"
    data.mkdir()
    runs = tmp_path / "runs"
    prior = runs / PRIOR_RUN_ID / "artifacts"
    prior.mkdir(parents=True)
    (prior / "obs.weights").write_bytes(b"w")
    return Settings(
        image="alex88ridolfi/presto5:png",
        data_dir=data.resolve(),
        runs_dir=runs.resolve(),
        outputs_dir=(tmp_path / "outputs").resolve(),
        default_cpus=2.0, default_memory_mb=1024, default_timeout_s=60,
        network="none", skip_healthcheck=True,
    )


def test_weights_to_ignorechan_parses_stdout(settings: Settings) -> None:
    backend = FakeDockerBackend(
        responses={
            "weights_to_ignorechan.py": FakeResponse(
                stdout="Loaded weights.\n0:31,64,96:99\n",
                status=RunStatus.SUCCESS,
            )
        }
    )
    result = run_weights_to_ignorechan(
        f"{PRIOR_RUN_ID}/artifacts/obs.weights",
        backend=backend,
        threshold=0.7,
        settings=settings,
    )
    assert result.status == RunStatus.SUCCESS
    assert result.result is not None
    # 0..31 (32) + 64 + 96..99 (4) = 37
    assert len(result.result.ignore_channels) == 37
    assert 64 in result.result.ignore_channels

    argv = backend.calls[0].invocation.argv
    assert "weights_to_ignorechan.py" in argv
    assert "-t" in argv and "0.7" in argv
    assert f"/runs/{PRIOR_RUN_ID}/artifacts/obs.weights" in argv


def test_weights_to_ignorechan_rejects_bad_threshold(settings: Settings) -> None:
    backend = FakeDockerBackend()
    with pytest.raises(PolicyViolationError):
        run_weights_to_ignorechan(
            f"{PRIOR_RUN_ID}/artifacts/obs.weights",
            backend=backend,
            threshold=2.0,
            settings=settings,
        )
    assert backend.calls == []
