"""Integration test for presto.simple_zapbirds with FakeDockerBackend."""

from __future__ import annotations

from pathlib import Path

import pytest

from presto_mcp.config import Settings
from presto_mcp.errors import DockerInvocationError, PathSecurityError
from presto_mcp.manifest import load_manifest
from presto_mcp.models import RunStatus
from presto_mcp.tools.simple_zapbirds import run_simple_zapbirds
from tests.fakes.fake_docker_backend import FakeDockerBackend, FakeResponse

PRIOR_RUN_ID = "20260517T120000Z-ZZZZZZ"
_SOURCE_FFT_BYTES = b"ORIGINAL-FFT-CONTENT"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    data = tmp_path / "data"
    data.mkdir()
    (data / "known.birds").write_bytes(b"60.0 1 0 0 0\n")
    runs = tmp_path / "runs"
    prior = runs / PRIOR_RUN_ID / "artifacts"
    prior.mkdir(parents=True)
    (prior / "prep.fft").write_bytes(_SOURCE_FFT_BYTES)
    (prior / "prep.inf").write_bytes(b"hdr")
    return Settings(
        image="alex88ridolfi/presto5:png",
        data_dir=data.resolve(),
        runs_dir=runs.resolve(),
        outputs_dir=(tmp_path / "outputs").resolve(),
        default_cpus=2.0, default_memory_mb=1024, default_timeout_s=60,
        network="none", skip_healthcheck=True,
    )


def test_simple_zapbirds_never_modifies_source(settings: Settings) -> None:
    # The fake "zaps" by overwriting the staged copy — the source must survive.
    backend = FakeDockerBackend(
        responses={
            "simple_zapbirds.py": FakeResponse(
                stdout="zapped\n",
                status=RunStatus.SUCCESS,
                artifacts={"prep.fft": b"ZAPPED-FFT-CONTENT"},
            )
        },
        probe_responses={
            "which:simple_zapbirds.py": FakeResponse(status=RunStatus.SUCCESS)
        },
    )
    result = run_simple_zapbirds(
        f"{PRIOR_RUN_ID}/artifacts/prep.fft",
        "known.birds",
        backend=backend, settings=settings,
    )
    assert result.status == RunStatus.SUCCESS

    source = settings.runs_dir / PRIOR_RUN_ID / "artifacts" / "prep.fft"
    assert source.read_bytes() == _SOURCE_FFT_BYTES  # source untouched

    run_dir = settings.runs_dir / result.run_id
    staged = run_dir / "artifacts" / "prep.fft"
    assert staged.read_bytes() == b"ZAPPED-FFT-CONTENT"  # only the copy changed

    assert result.result is not None
    assert result.result.zapped_fft_files == ["prep.fft"]
    assert result.result.birds_file == "known.birds"

    run_call = next(
        c for c in backend.calls
        if c.invocation.argv[c.invocation.argv.index(c.invocation.image) + 1]
        == "simple_zapbirds.py"
    )
    argv = run_call.invocation.argv
    assert "simple_zapbirds.py" in argv
    assert "prep.fft" in argv and "known.birds" in argv
    assert load_manifest(run_dir).tool == "simple_zapbirds"


def test_simple_zapbirds_blocks_when_routine_missing(settings: Settings) -> None:
    backend = FakeDockerBackend(
        probe_responses={
            "which:simple_zapbirds.py": FakeResponse(
                status=RunStatus.FAILED, exit_code=1
            )
        }
    )
    with pytest.raises(DockerInvocationError, match="simple_zapbirds"):
        run_simple_zapbirds(
            f"{PRIOR_RUN_ID}/artifacts/prep.fft", "known.birds",
            backend=backend, settings=settings,
        )


def test_simple_zapbirds_rejects_absolute_path(settings: Settings) -> None:
    backend = FakeDockerBackend()
    with pytest.raises(PathSecurityError):
        run_simple_zapbirds(
            "/etc/passwd", "known.birds", backend=backend, settings=settings,
        )
