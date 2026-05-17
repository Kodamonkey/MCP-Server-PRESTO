"""Integration test for presto.makezaplist (experimental)."""

from __future__ import annotations

from pathlib import Path

import pytest

from presto_mcp.config import Settings
from presto_mcp.models import RunStatus
from presto_mcp.tools.makezaplist import run_makezaplist
from tests.fakes.fake_docker_backend import FakeDockerBackend, FakeResponse


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    data = tmp_path / "data"
    data.mkdir()
    (data / "rfi.birds").write_text("# birds file\n100.0 0.01 10 0 0\n")
    return Settings(
        image="alex88ridolfi/presto5:png",
        data_dir=data.resolve(),
        runs_dir=(tmp_path / "runs").resolve(),
        outputs_dir=(tmp_path / "outputs").resolve(),
        logs_dir=(tmp_path / "logs").resolve(),
        default_cpus=2.0, default_memory_mb=1024, default_timeout_s=60,
        network="none", skip_healthcheck=True,
    )


def test_makezaplist_success(settings: Settings) -> None:
    backend = FakeDockerBackend(
        responses={
            "makezaplist.py": FakeResponse(
                stdout="wrote rfi.zaplist\n",
                status=RunStatus.SUCCESS,
                artifacts={"rfi.zaplist": b"100.0 0.01 10\n"},
            )
        }
    )
    result = run_makezaplist("rfi.birds", backend=backend, settings=settings)
    assert result.status == RunStatus.SUCCESS
    assert result.result is not None
    assert result.result.zaplist_file == "rfi.zaplist"

    argv = backend.calls[0].invocation.argv
    assert "makezaplist.py" in argv
    assert "/data/rfi.birds" in argv
