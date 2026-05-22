"""Integration test for sifting with FakeDockerBackend."""

from __future__ import annotations

from pathlib import Path

import pytest

from presto_mcp.config import Settings
from presto_mcp.errors import PathSecurityError, PolicyViolationError
from presto_mcp.manifest import load_manifest
from presto_mcp.models import RunStatus
from presto_mcp.tools.sifting import run_sifting
from tests.fakes.fake_docker_backend import FakeDockerBackend, FakeResponse

PRIOR_RUN_ID = "20260517T120000Z-DDDDDD"

_SIFT_STDOUT = """\
Reading candidates...
Total candidates: 100
Sifting candidates...
# DM       Sigma     Period(ms)   Freq(Hz)    Hits
  56.78    11.32     8.103        123.456     3

Surviving candidates: 1
Done.
"""


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    data = tmp_path / "data"
    data.mkdir()
    runs = tmp_path / "runs"
    prior = runs / PRIOR_RUN_ID / "artifacts"
    prior.mkdir(parents=True)
    for name in ("a_ACCEL_200", "b_ACCEL_200"):
        (prior / name).write_bytes(b"X")
        # sibling .inf companion
        base = name.split("_ACCEL_")[0]
        (prior / f"{base}.inf").write_bytes(b"i")
    return Settings(
        image="alex88ridolfi/presto5:png",
        data_dir=data.resolve(),
        runs_dir=runs.resolve(),
        outputs_dir=(tmp_path / "outputs").resolve(),
        default_cpus=2.0, default_memory_mb=1024, default_timeout_s=60,
        network="none", skip_healthcheck=True,
    )


def test_sifting_stages_and_argv(settings: Settings) -> None:
    backend = FakeDockerBackend(
        responses={
            "/software/presto5/examplescripts/ACCEL_sift.py": FakeResponse(
                stdout=_SIFT_STDOUT, status=RunStatus.SUCCESS
            )
        }
    )
    result = run_sifting(
        [
            f"{PRIOR_RUN_ID}/artifacts/a_ACCEL_200",
            f"{PRIOR_RUN_ID}/artifacts/b_ACCEL_200",
        ],
        backend=backend,
        min_num_dms=2, low_dm_cutoff=2.0, sigma_threshold=4.0,
        settings=settings,
    )
    assert result.status == RunStatus.SUCCESS
    assert result.result is not None
    assert result.result.total_input_cands == 100
    assert result.result.total_surviving == 1
    assert len(result.result.surviving_candidates) == 1

    argv = backend.calls[0].invocation.argv
    assert "/software/presto5/examplescripts/ACCEL_sift.py" in argv
    assert "--minDMs" in argv and "2" in argv
    assert "--lowDM" in argv
    assert "--sigma" in argv
    assert "--workdir" in argv and "/outputs/staging" in argv

    # staging/ populated with both accel files + .inf companions.
    staging = settings.runs_dir / result.run_id / "staging"
    assert staging.is_dir()
    staged = {p.name for p in staging.iterdir()}
    assert "a_ACCEL_200" in staged
    assert "b_ACCEL_200" in staged
    assert "a.inf" in staged
    assert "b.inf" in staged

    m = load_manifest(settings.runs_dir / result.run_id)
    assert m.tool == "sifting"


def test_sifting_rejects_empty_list(settings: Settings) -> None:
    backend = FakeDockerBackend()
    with pytest.raises(PolicyViolationError):
        run_sifting([], backend=backend, settings=settings)


def test_sifting_rejects_bad_path(settings: Settings) -> None:
    backend = FakeDockerBackend()
    with pytest.raises(PathSecurityError):
        run_sifting(
            [f"{PRIOR_RUN_ID}/artifacts/a_ACCEL_200", "../escape"],
            backend=backend, settings=settings,
        )
