"""Integration test for presto.downsample_filterbank with FakeDockerBackend."""

from __future__ import annotations

from pathlib import Path

import pytest

from presto_mcp.config import Settings
from presto_mcp.errors import PolicyViolationError
from presto_mcp.models import RunStatus
from presto_mcp.tools.downsample_filterbank import run_downsample_filterbank
from tests.fakes.fake_docker_backend import FakeDockerBackend, FakeResponse


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    data = tmp_path / "data"
    data.mkdir()
    (data / "obs.fil").write_bytes(b"\x00" * 16)
    return Settings(
        image="alex88ridolfi/presto5:png",
        data_dir=data.resolve(),
        runs_dir=(tmp_path / "runs").resolve(),
        outputs_dir=(tmp_path / "outputs").resolve(),
        default_cpus=2.0,
        default_memory_mb=1024,
        default_timeout_s=60,
        network="none",
        skip_healthcheck=True,
    )


def test_downsample_success(settings: Settings) -> None:
    backend = FakeDockerBackend(
        responses={
            "downsample_filterbank.py": FakeResponse(
                stdout="ok\n",
                status=RunStatus.SUCCESS,
                artifacts={"obs_DS8.fil": b"\x01\x01"},
            )
        }
    )
    result = run_downsample_filterbank(
        "obs.fil", backend=backend, factor=8, settings=settings
    )
    assert result.status == RunStatus.SUCCESS
    assert result.result is not None
    assert result.result.factor == 8
    assert result.result.output_file == "obs_DS8.fil"

    argv = backend.calls[0].invocation.argv
    assert "downsample_filterbank.py" in argv
    assert "8" in argv
    assert "/data/obs.fil" in argv


@pytest.mark.parametrize("bad_factor", [0, 1, 2048, -3])
def test_downsample_rejects_bad_factor(settings: Settings, bad_factor: int) -> None:
    backend = FakeDockerBackend()
    with pytest.raises(PolicyViolationError):
        run_downsample_filterbank(
            "obs.fil", backend=backend, factor=bad_factor, settings=settings
        )
    assert backend.calls == []
