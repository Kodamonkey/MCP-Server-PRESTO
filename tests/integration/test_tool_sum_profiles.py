"""Integration test for presto.sum_profiles (experimental)."""

from __future__ import annotations

from pathlib import Path

import pytest

from presto_mcp.config import Settings
from presto_mcp.errors import PolicyViolationError
from presto_mcp.models import RunStatus
from presto_mcp.tools.sum_profiles import run_sum_profiles
from tests.fakes.fake_docker_backend import FakeDockerBackend, FakeResponse

PRIOR_RUN_ID = "20260517T120000Z-FFFFFF"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    data = tmp_path / "data"
    data.mkdir()
    runs = tmp_path / "runs"
    prior = runs / PRIOR_RUN_ID / "artifacts"
    prior.mkdir(parents=True)
    for n in ("a.bestprof", "b.bestprof"):
        (prior / n).write_text("# fake bestprof\n")
    return Settings(
        image="alex88ridolfi/presto5:png",
        data_dir=data.resolve(),
        runs_dir=runs.resolve(),
        outputs_dir=(tmp_path / "outputs").resolve(),
        logs_dir=(tmp_path / "logs").resolve(),
        default_cpus=2.0, default_memory_mb=1024, default_timeout_s=60,
        network="none", skip_healthcheck=True,
    )


def test_sum_profiles_multi_input(settings: Settings) -> None:
    backend = FakeDockerBackend(
        responses={
            "sum_profiles.py": FakeResponse(
                stdout="summed\n",
                status=RunStatus.SUCCESS,
                artifacts={"sum.prof": b"summed"},
            )
        }
    )
    result = run_sum_profiles(
        [
            f"{PRIOR_RUN_ID}/artifacts/a.bestprof",
            f"{PRIOR_RUN_ID}/artifacts/b.bestprof",
        ],
        backend=backend,
        settings=settings,
    )
    assert result.status == RunStatus.SUCCESS
    assert result.result is not None
    assert result.result.output_profile_file == "sum.prof"
    assert len(result.result.input_profile_files) == 2

    argv = backend.calls[0].invocation.argv
    assert "sum_profiles.py" in argv
    assert f"/runs/{PRIOR_RUN_ID}/artifacts/a.bestprof" in argv
    assert f"/runs/{PRIOR_RUN_ID}/artifacts/b.bestprof" in argv


def test_sum_profiles_rejects_empty_list(settings: Settings) -> None:
    backend = FakeDockerBackend()
    with pytest.raises(PolicyViolationError):
        run_sum_profiles([], backend=backend, settings=settings)
    assert backend.calls == []
