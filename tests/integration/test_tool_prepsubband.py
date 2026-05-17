"""Integration test for prepsubband with FakeDockerBackend."""

from __future__ import annotations

from pathlib import Path

import pytest

from presto_mcp.config import Settings
from presto_mcp.errors import PolicyViolationError
from presto_mcp.manifest import load_manifest
from presto_mcp.models import RunStatus
from presto_mcp.tools.prepsubband import run_prepsubband
from tests.fakes.fake_docker_backend import FakeDockerBackend, FakeResponse


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    data = tmp_path / "data"
    data.mkdir()
    (data / "input.fil").write_bytes(b"\x00" * 16)
    return Settings(
        image="alex88ridolfi/presto5:png",
        data_dir=data.resolve(),
        runs_dir=(tmp_path / "runs").resolve(),
        outputs_dir=(tmp_path / "outputs").resolve(),
        logs_dir=(tmp_path / "logs").resolve(),
        default_cpus=2.0, default_memory_mb=1024, default_timeout_s=60,
        network="none", skip_healthcheck=True,
    )


def test_prepsubband_argv_and_artifacts(settings: Settings) -> None:
    artifacts = {f"sub_DM{i:.2f}.dat": b"D" for i in (0.0, 0.1, 0.2)}
    artifacts.update({f"sub_DM{i:.2f}.inf": b"I" for i in (0.0, 0.1, 0.2)})
    backend = FakeDockerBackend(
        responses={
            "prepsubband": FakeResponse(
                stdout="Working on DM = 0.00\nDone.\n",
                status=RunStatus.SUCCESS,
                artifacts=artifacts,
            )
        }
    )
    result = run_prepsubband(
        "input.fil",
        backend=backend,
        dm_low=0.0, dm_step=0.1, num_dms=3, num_subbands=32,
        settings=settings,
    )
    assert result.status == RunStatus.SUCCESS
    assert result.result is not None
    assert len(result.result.dat_files) == 3
    assert result.result.num_subbands == 32

    argv = backend.calls[0].invocation.argv
    assert "prepsubband" in argv
    assert "-lodm" in argv and "0.0" in argv
    assert "-dmstep" in argv and "0.1" in argv
    assert "-numdms" in argv and "3" in argv
    assert "-nsub" in argv and "32" in argv
    assert argv[-1] == "/data/input.fil"

    m = load_manifest(settings.runs_dir / result.run_id)
    assert m.tool == "prepsubband"


@pytest.mark.parametrize("step", [0.0, -1.0, 2000.0])
def test_prepsubband_rejects_bad_step(settings: Settings, step: float) -> None:
    backend = FakeDockerBackend()
    with pytest.raises(PolicyViolationError):
        run_prepsubband(
            "input.fil", backend=backend,
            dm_low=0.0, dm_step=step, num_dms=10, num_subbands=32,
            settings=settings,
        )
