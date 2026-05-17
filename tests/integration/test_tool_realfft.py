"""Integration test for realfft with FakeDockerBackend."""

from __future__ import annotations

from pathlib import Path

import pytest

from presto_mcp.config import Settings
from presto_mcp.errors import PathSecurityError
from presto_mcp.manifest import load_manifest
from presto_mcp.models import RunStatus
from presto_mcp.tools.realfft import run_realfft
from tests.fakes.fake_docker_backend import FakeDockerBackend, FakeResponse

PRIOR_RUN_ID = "20260517T120000Z-AAAAAA"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    data = tmp_path / "data"
    data.mkdir()

    runs = tmp_path / "runs"
    prior_artifacts = runs / PRIOR_RUN_ID / "artifacts"
    prior_artifacts.mkdir(parents=True)
    (prior_artifacts / "prep.dat").write_bytes(b"\x00" * 32)
    (prior_artifacts / "prep.inf").write_bytes(b"hdr")

    return Settings(
        image="alex88ridolfi/presto5:png",
        data_dir=data.resolve(),
        runs_dir=runs.resolve(),
        outputs_dir=(tmp_path / "outputs").resolve(),
        logs_dir=(tmp_path / "logs").resolve(),
        default_cpus=2.0, default_memory_mb=1024, default_timeout_s=60,
        network="none", skip_healthcheck=True,
    )


def test_realfft_stages_input_and_argv(settings: Settings) -> None:
    backend = FakeDockerBackend(
        responses={
            "realfft": FakeResponse(
                stdout="",
                status=RunStatus.SUCCESS,
                artifacts={"prep.fft": b"FFT"},
            )
        }
    )
    result = run_realfft(
        f"{PRIOR_RUN_ID}/artifacts/prep.dat",
        backend=backend, settings=settings,
    )
    assert result.status == RunStatus.SUCCESS
    assert result.result is not None
    assert result.result.fft_file == "prep.fft"
    assert result.result.input_dat == "prep.dat"

    # .dat + .inf staged into the new run's artifacts/.
    run_dir = settings.runs_dir / result.run_id
    assert (run_dir / "artifacts" / "prep.dat").is_file()
    assert (run_dir / "artifacts" / "prep.inf").is_file()

    argv = backend.calls[0].invocation.argv
    assert "realfft" in argv
    assert "/outputs/artifacts/prep.dat" in argv

    m = load_manifest(run_dir)
    assert m.tool == "realfft"


def test_realfft_rejects_non_dat(settings: Settings) -> None:
    runs = settings.runs_dir
    (runs / PRIOR_RUN_ID / "artifacts" / "prep.fft").write_bytes(b"F")
    backend = FakeDockerBackend()
    with pytest.raises(PathSecurityError, match=".dat"):
        run_realfft(
            f"{PRIOR_RUN_ID}/artifacts/prep.fft",
            backend=backend, settings=settings,
        )
    assert backend.calls == []


def test_realfft_rejects_bad_path(settings: Settings) -> None:
    backend = FakeDockerBackend()
    with pytest.raises(PathSecurityError):
        run_realfft("not-a-runid/artifacts/x.dat", backend=backend, settings=settings)
