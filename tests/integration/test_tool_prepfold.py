"""Integration test for the prepfold tool (Mode A) with FakeDockerBackend.

A real prepfold run requires a true pulsar candidate. We don't have one bundled,
so the MVP test only verifies argv construction + policy + artifact wiring with
a synthetic backend response.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from presto_mcp.config import Settings
from presto_mcp.errors import PolicyViolationError
from presto_mcp.manifest import load_manifest
from presto_mcp.models import RunStatus
from presto_mcp.tools.prepfold import run_prepfold
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
        default_cpus=2.0,
        default_memory_mb=1024,
        default_timeout_s=60,
        network="none",
        skip_healthcheck=True,
    )


def test_prepfold_argv_and_artifacts(settings: Settings) -> None:
    backend = FakeDockerBackend(
        responses={
            "prepfold": FakeResponse(
                stdout="prepfold ok\n",
                status=RunStatus.SUCCESS,
                artifacts={
                    "fold_test.pfd": b"P",
                    "fold_test.pfd.ps": b"S",
                    "fold_test.pfd.bestprof": b"B",
                },
            )
        }
    )
    result = run_prepfold(
        "input.fil",
        period_s=0.05,
        dm=56.78,
        output_prefix="fold_test",
        backend=backend,
        settings=settings,
    )

    assert result.status == RunStatus.SUCCESS
    assert result.result is not None
    assert result.result.period_s == 0.05
    assert result.result.dm == 56.78
    assert result.result.output_prefix == "fold_test"
    assert result.result.pfd_file == "fold_test.pfd"
    assert result.result.ps_file == "fold_test.pfd.ps"
    assert result.result.bestprof_file == "fold_test.pfd.bestprof"

    argv = backend.calls[0].invocation.argv
    assert "prepfold" in argv
    assert "-noxwin" in argv
    assert "-nosearch" in argv
    assert "-p" in argv
    assert "-dm" in argv
    assert "/outputs/artifacts/fold_test" in argv
    assert argv[-1] == "/data/input.fil"

    m = load_manifest(settings.runs_dir / result.run_id)
    assert m.tool == "prepfold"
    assert "0.05" in m.presto_argv
    assert "56.78" in m.presto_argv


@pytest.mark.parametrize("period", [0.0, -1.0, 1e-9, 70.0])
def test_prepfold_rejects_bad_period(settings: Settings, period: float) -> None:
    backend = FakeDockerBackend()
    with pytest.raises(PolicyViolationError):
        run_prepfold("input.fil", period_s=period, dm=10.0, backend=backend, settings=settings)
    assert backend.calls == []


@pytest.mark.parametrize("dm", [-0.001, 10_001.0])
def test_prepfold_rejects_bad_dm(settings: Settings, dm: float) -> None:
    backend = FakeDockerBackend()
    with pytest.raises(PolicyViolationError):
        run_prepfold("input.fil", period_s=0.5, dm=dm, backend=backend, settings=settings)
    assert backend.calls == []
