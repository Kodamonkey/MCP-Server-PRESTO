"""Integration test for ddplan with FakeDockerBackend."""

from __future__ import annotations

from pathlib import Path

import pytest

from presto_mcp.config import Settings
from presto_mcp.errors import PolicyViolationError
from presto_mcp.manifest import load_manifest
from presto_mcp.models import RunStatus
from presto_mcp.tools.ddplan import run_ddplan
from tests.fakes.fake_docker_backend import FakeDockerBackend, FakeResponse

_STDOUT = """\
DDplan results

  Low DM    High DM   dDM     DownSamp   dsubDM   #DMs   WorkFract
  --------  --------  ------  ---------  -------  -----  ---------
  0.000     50.000    0.10    1          4.00     500    1.0

Total work fraction: 1.0
"""


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    data = tmp_path / "data"
    data.mkdir()
    return Settings(
        image="alex88ridolfi/presto5:png",
        data_dir=data.resolve(),
        runs_dir=(tmp_path / "runs").resolve(),
        outputs_dir=(tmp_path / "outputs").resolve(),
        logs_dir=(tmp_path / "logs").resolve(),
        default_cpus=2.0, default_memory_mb=1024, default_timeout_s=60,
        network="none", skip_healthcheck=True,
    )


def test_ddplan_argv_and_plan(settings: Settings) -> None:
    backend = FakeDockerBackend(
        responses={"DDplan.py": FakeResponse(stdout=_STDOUT, status=RunStatus.SUCCESS)}
    )
    result = run_ddplan(
        backend=backend,
        dm_low=0.0, dm_high=50.0,
        freq_mhz=1564.25, bw_mhz=336.0,
        num_channels=672, sample_time_us=64.0,
        settings=settings,
    )
    assert result.status == RunStatus.SUCCESS
    assert result.result is not None
    assert len(result.result.passes) == 1
    assert result.result.passes[0].dms_per_call == 500
    assert result.result.num_dms == 500

    argv = backend.calls[0].invocation.argv
    assert "DDplan.py" in argv
    assert "-l" in argv and "0.0" in argv
    assert "-d" in argv and "50.0" in argv
    assert "-f" in argv and "1564.25" in argv
    assert "-b" in argv and "336.0" in argv
    assert "-n" in argv and "672" in argv
    assert "-t" in argv

    m = load_manifest(settings.runs_dir / result.run_id)
    assert m.tool == "ddplan"
    assert "input_file" not in m.container_inputs


def test_ddplan_rejects_inverted_range(settings: Settings) -> None:
    backend = FakeDockerBackend()
    with pytest.raises(PolicyViolationError):
        run_ddplan(
            backend=backend,
            dm_low=100.0, dm_high=50.0,
            freq_mhz=1500.0, bw_mhz=300.0,
            num_channels=512, sample_time_us=64.0,
            settings=settings,
        )
