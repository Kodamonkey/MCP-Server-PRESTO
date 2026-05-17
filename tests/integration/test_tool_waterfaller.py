"""Integration test for waterfaller with FakeDockerBackend."""

from __future__ import annotations

from pathlib import Path

import pytest

from presto_mcp.config import Settings
from presto_mcp.errors import PolicyViolationError
from presto_mcp.manifest import load_manifest
from presto_mcp.models import RunStatus
from presto_mcp.tools.waterfaller import run_waterfaller
from tests.fakes.fake_docker_backend import FakeDockerBackend, FakeResponse


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    data = tmp_path / "data"
    data.mkdir()
    (data / "raw.fil").write_bytes(b"FIL" * 64)
    (data / "rfi.mask").write_bytes(b"M" * 16)
    runs = tmp_path / "runs"
    runs.mkdir()
    return Settings(
        image="alex88ridolfi/presto5:png",
        data_dir=data.resolve(),
        runs_dir=runs.resolve(),
        outputs_dir=(tmp_path / "outputs").resolve(),
        logs_dir=(tmp_path / "logs").resolve(),
        default_cpus=2.0, default_memory_mb=1024, default_timeout_s=60,
        network="none", skip_healthcheck=True,
    )


def test_waterfaller_argv_and_png(settings: Settings) -> None:
    backend = FakeDockerBackend(
        responses={
            "python": FakeResponse(
                stdout="rendered\n",
                status=RunStatus.SUCCESS,
                artifacts={"waterfall.png": b"\x89PNG"},
            )
        }
    )
    result = run_waterfaller(
        "raw.fil",
        backend=backend, settings=settings,
        start_s=12.5, duration_s=0.25, dm=56.78,
        mask_file="rfi.mask", nsub=32, nbins=128, downsamp=2,
    )
    assert result.status == RunStatus.SUCCESS
    assert result.result is not None
    assert result.result.output_file == "waterfall.png"
    assert result.result.start_s == 12.5
    assert result.result.dm == 56.78

    argv = backend.calls[0].invocation.argv
    assert "python" in argv
    assert "/outputs/artifacts/waterfaller_headless.py" in argv
    assert "-T" in argv and "12.5" in argv
    assert "-t" in argv and "0.25" in argv
    assert "-d" in argv and "56.78" in argv
    assert "--mask" in argv
    assert "--maskfile" in argv and "/data/rfi.mask" in argv
    assert "/data/raw.fil" in argv
    assert "--workdir" in argv and "/outputs/artifacts" in argv

    run_dir = settings.runs_dir / result.run_id
    assert (run_dir / "artifacts" / "waterfaller_headless.py").is_file()
    m = load_manifest(run_dir)
    assert m.tool == "waterfaller"


def test_waterfaller_rejects_huge_duration(settings: Settings) -> None:
    backend = FakeDockerBackend()
    with pytest.raises(PolicyViolationError):
        run_waterfaller(
            "raw.fil",
            backend=backend, settings=settings,
            start_s=0.0, duration_s=99999.0, dm=10.0,
        )
