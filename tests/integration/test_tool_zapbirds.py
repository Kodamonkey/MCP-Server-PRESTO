"""Integration test for zapbirds with FakeDockerBackend."""

from __future__ import annotations

from pathlib import Path

import pytest

from presto_mcp.config import Settings
from presto_mcp.errors import PathSecurityError, PolicyViolationError
from presto_mcp.manifest import load_manifest
from presto_mcp.models import RunStatus
from presto_mcp.tools.zapbirds import run_zapbirds
from tests.fakes.fake_docker_backend import FakeDockerBackend, FakeResponse

PRIOR_RUN_ID = "20260517T120000Z-ZZZZZZ"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    data = tmp_path / "data"
    data.mkdir()
    (data / "zaplist.txt").write_text("0.1 0.01\n0.5 0.05\n", encoding="utf-8")

    runs = tmp_path / "runs"
    prior = runs / PRIOR_RUN_ID / "artifacts"
    prior.mkdir(parents=True)
    (prior / "prep.fft").write_bytes(b"\x00" * 32)
    (prior / "prep.inf").write_bytes(b"hdr")

    return Settings(
        image="alex88ridolfi/presto5:png",
        data_dir=data.resolve(),
        runs_dir=runs.resolve(),
        outputs_dir=(tmp_path / "outputs").resolve(),
        logs_dir=(tmp_path / "logs").resolve(),
        default_cpus=2.0, default_memory_mb=1024, default_timeout_s=60,
        network="none", skip_healthcheck=True,
    )


def test_zapbirds_argv_and_staging(settings: Settings) -> None:
    backend = FakeDockerBackend(
        responses={
            "zapbirds": FakeResponse(
                stdout="Read 2 frequencies to zap from the zaplist\n",
                status=RunStatus.SUCCESS,
                artifacts={"prep.fft": b"ZAPPED"},
            )
        }
    )
    result = run_zapbirds(
        f"{PRIOR_RUN_ID}/artifacts/prep.fft",
        "zaplist.txt",
        backend=backend, settings=settings,
    )
    assert result.status == RunStatus.SUCCESS
    assert result.result is not None
    assert result.result.zapped_fft == "prep.fft"
    assert result.result.num_zaps == 2

    run_dir = settings.runs_dir / result.run_id
    assert (run_dir / "artifacts" / "prep.fft").is_file()
    assert (run_dir / "artifacts" / "prep.inf").is_file()

    argv = backend.calls[0].invocation.argv
    assert "zapbirds" in argv
    assert "-zap" in argv
    assert "-zaplist" in argv
    assert "/data/zaplist.txt" in argv
    assert "/outputs/artifacts/prep.fft" in argv

    m = load_manifest(run_dir)
    assert m.tool == "zapbirds"


def test_zapbirds_rejects_non_fft(settings: Settings) -> None:
    backend = FakeDockerBackend()
    with pytest.raises(PathSecurityError, match=".fft"):
        run_zapbirds(
            f"{PRIOR_RUN_ID}/artifacts/prep.inf",
            "zaplist.txt",
            backend=backend, settings=settings,
        )
    assert backend.calls == []


def test_zapbirds_baryv_bounds(settings: Settings) -> None:
    backend = FakeDockerBackend()
    with pytest.raises(PolicyViolationError):
        run_zapbirds(
            f"{PRIOR_RUN_ID}/artifacts/prep.fft",
            "zaplist.txt",
            backend=backend, settings=settings, baryv=99.0,
        )
