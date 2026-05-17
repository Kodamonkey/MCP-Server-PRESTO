"""Integration test for single_pulse_search with FakeDockerBackend."""

from __future__ import annotations

from pathlib import Path

import pytest

from presto_mcp.config import Settings
from presto_mcp.errors import PathSecurityError, PolicyViolationError
from presto_mcp.manifest import load_manifest
from presto_mcp.models import RunStatus
from presto_mcp.tools.single_pulse_search import run_single_pulse_search
from tests.fakes.fake_docker_backend import FakeDockerBackend, FakeResponse

PRIOR_RUN_ID = "20260517T120000Z-CCCCCC"

_SP = """\
# DM   Sigma  Time  Sample  Downfact
  56.78  6.20  12.3  12345  2
"""


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    data = tmp_path / "data"
    data.mkdir()
    runs = tmp_path / "runs"
    prior = runs / PRIOR_RUN_ID / "artifacts"
    prior.mkdir(parents=True)
    for dm in ("0.00", "0.10"):
        (prior / f"sub_DM{dm}.dat").write_bytes(b"d")
        (prior / f"sub_DM{dm}.inf").write_bytes(b"i")
    return Settings(
        image="alex88ridolfi/presto5:png",
        data_dir=data.resolve(),
        runs_dir=runs.resolve(),
        outputs_dir=(tmp_path / "outputs").resolve(),
        logs_dir=(tmp_path / "logs").resolve(),
        default_cpus=2.0, default_memory_mb=1024, default_timeout_s=60,
        network="none", skip_healthcheck=True,
    )


def test_single_pulse_search_argv_and_artifacts(settings: Settings) -> None:
    backend = FakeDockerBackend(
        responses={
            "single_pulse_search.py": FakeResponse(
                stdout="searched\n",
                status=RunStatus.SUCCESS,
                artifacts={
                    "sub_DM0.00.singlepulse": _SP.encode("utf-8"),
                    "sub_DM0.10.singlepulse": _SP.encode("utf-8"),
                },
            )
        }
    )
    result = run_single_pulse_search(
        [
            f"{PRIOR_RUN_ID}/artifacts/sub_DM0.00.dat",
            f"{PRIOR_RUN_ID}/artifacts/sub_DM0.10.dat",
        ],
        backend=backend, threshold=5.0, max_width_s=0.05,
        settings=settings,
    )
    assert result.status == RunStatus.SUCCESS
    assert result.result is not None
    assert len(result.result.singlepulse_files) == 2
    assert result.result.pulse_count == 2

    argv = backend.calls[0].invocation.argv
    assert "single_pulse_search.py" in argv
    assert "-t" in argv and "5.0" in argv
    assert "-m" in argv and "0.05" in argv
    assert "/outputs/artifacts/sub_DM0.00.dat" in argv
    assert "/outputs/artifacts/sub_DM0.10.dat" in argv

    # Inputs staged into new run's artifacts/.
    run_dir = settings.runs_dir / result.run_id
    assert (run_dir / "artifacts" / "sub_DM0.00.dat").is_file()
    assert (run_dir / "artifacts" / "sub_DM0.10.dat").is_file()

    m = load_manifest(run_dir)
    assert m.tool == "single_pulse_search"


def test_single_pulse_search_rejects_empty_list(settings: Settings) -> None:
    backend = FakeDockerBackend()
    with pytest.raises(PolicyViolationError):
        run_single_pulse_search([], backend=backend, settings=settings)


def test_single_pulse_search_rejects_bad_path(settings: Settings) -> None:
    backend = FakeDockerBackend()
    with pytest.raises(PathSecurityError):
        run_single_pulse_search(
            [f"{PRIOR_RUN_ID}/artifacts/sub_DM0.00.dat", "../escape.dat"],
            backend=backend, settings=settings,
        )
