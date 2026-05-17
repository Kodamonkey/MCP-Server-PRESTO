"""Integration test for presto.pfd2png (experimental)."""

from __future__ import annotations

from pathlib import Path

import pytest

from presto_mcp.config import Settings
from presto_mcp.models import RunStatus
from presto_mcp.tools.pfd2png import run_pfd2png
from tests.fakes.fake_docker_backend import FakeDockerBackend, FakeResponse

PRIOR_RUN_ID = "20260517T120000Z-BBBBBB"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    data = tmp_path / "data"
    data.mkdir()
    runs = tmp_path / "runs"
    prior = runs / PRIOR_RUN_ID / "artifacts"
    prior.mkdir(parents=True)
    (prior / "fold.pfd").write_bytes(b"P" * 16)
    return Settings(
        image="alex88ridolfi/presto5:png",
        data_dir=data.resolve(),
        runs_dir=runs.resolve(),
        outputs_dir=(tmp_path / "outputs").resolve(),
        logs_dir=(tmp_path / "logs").resolve(),
        default_cpus=2.0, default_memory_mb=1024, default_timeout_s=60,
        network="none", skip_healthcheck=True,
    )


def test_pfd2png_produces_png(settings: Settings) -> None:
    backend = FakeDockerBackend(
        responses={
            "pfd2png.sh": FakeResponse(
                stdout="rendered\n",
                status=RunStatus.SUCCESS,
                artifacts={"fold.png": b"\x89PNG"},
            )
        }
    )
    result = run_pfd2png(
        f"{PRIOR_RUN_ID}/artifacts/fold.pfd",
        backend=backend,
        settings=settings,
    )
    assert result.status == RunStatus.SUCCESS
    assert result.result is not None
    assert result.result.png_file == "fold.png"

    argv = backend.calls[0].invocation.argv
    assert "pfd2png.sh" in argv
    assert "fold.pfd" in argv


def test_pfd2png_handles_missing_binary(settings: Settings) -> None:
    backend = FakeDockerBackend(
        responses={
            "pfd2png.sh": FakeResponse(
                stdout="bash: pfd2png.sh: command not found\n",
                exit_code=127,
                status=RunStatus.SUCCESS,  # ran, no output
            )
        }
    )
    result = run_pfd2png(
        f"{PRIOR_RUN_ID}/artifacts/fold.pfd",
        backend=backend,
        settings=settings,
    )
    assert result.status == RunStatus.SUCCESS
    assert result.result is not None
    assert result.result.png_file is None
    assert any("pfd2png" in n for n in result.result.notes)
