"""Integration test for presto.stacksearch with FakeDockerBackend."""

from __future__ import annotations

from pathlib import Path

import pytest

from presto_mcp.config import Settings
from presto_mcp.errors import DockerInvocationError, PathSecurityError, PolicyViolationError
from presto_mcp.manifest import load_manifest
from presto_mcp.models import RunStatus
from presto_mcp.tools.stacksearch import run_stacksearch
from tests.fakes.fake_docker_backend import FakeDockerBackend, FakeResponse

PRIOR_RUN_ID = "20260517T120000Z-SSSSSS"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    data = tmp_path / "data"
    data.mkdir()
    runs = tmp_path / "runs"
    prior = runs / PRIOR_RUN_ID / "artifacts"
    prior.mkdir(parents=True)
    for name in ("a.fft", "b.fft"):
        (prior / name).write_bytes(b"FFT")
        (prior / name.replace(".fft", ".inf")).write_bytes(b"hdr")
    return Settings(
        image="alex88ridolfi/presto5:png",
        data_dir=data.resolve(),
        runs_dir=runs.resolve(),
        outputs_dir=(tmp_path / "outputs").resolve(),
        logs_dir=(tmp_path / "logs").resolve(),
        default_cpus=2.0, default_memory_mb=1024, default_timeout_s=60,
        network="none", skip_healthcheck=True,
    )


def test_stacksearch_argv_and_staging(settings: Settings) -> None:
    backend = FakeDockerBackend(
        responses={
            "stacksearch.py": FakeResponse(
                stdout="stacking...\n",
                status=RunStatus.SUCCESS,
                artifacts={"stack_cands.txtcand": b"#\n 1 12.3 0.0 100.0\n"},
            )
        },
        probe_responses={"which:stacksearch.py": FakeResponse(status=RunStatus.SUCCESS)},
    )
    result = run_stacksearch(
        [f"{PRIOR_RUN_ID}/artifacts/a.fft", f"{PRIOR_RUN_ID}/artifacts/b.fft"],
        backend=backend, settings=settings,
    )
    assert result.status == RunStatus.SUCCESS
    run_call = next(
        c for c in backend.calls
        if c.invocation.argv[c.invocation.argv.index(c.invocation.image) + 1]
        == "stacksearch.py"
    )
    argv = run_call.invocation.argv
    assert "stacksearch.py" in argv
    assert "a.fft" in argv and "b.fft" in argv
    assert "--workdir" in argv and "/outputs/artifacts" in argv

    run_dir = settings.runs_dir / result.run_id
    assert (run_dir / "artifacts" / "a.fft").is_file()
    assert result.result is not None
    assert "stack_cands.txtcand" in result.result.candidate_files
    assert load_manifest(run_dir).tool == "stacksearch"


def test_stacksearch_blocks_when_routine_missing(settings: Settings) -> None:
    backend = FakeDockerBackend(
        probe_responses={
            "which:stacksearch.py": FakeResponse(
                status=RunStatus.FAILED, exit_code=1
            )
        }
    )
    with pytest.raises(DockerInvocationError, match="stacksearch"):
        run_stacksearch(
            [f"{PRIOR_RUN_ID}/artifacts/a.fft", f"{PRIOR_RUN_ID}/artifacts/b.fft"],
            backend=backend, settings=settings,
        )


def test_stacksearch_requires_two_files(settings: Settings) -> None:
    backend = FakeDockerBackend()
    with pytest.raises(PolicyViolationError):
        run_stacksearch(
            [f"{PRIOR_RUN_ID}/artifacts/a.fft"], backend=backend, settings=settings,
        )


def test_stacksearch_rejects_absolute_path(settings: Settings) -> None:
    backend = FakeDockerBackend()
    with pytest.raises(PathSecurityError):
        run_stacksearch(
            [f"{PRIOR_RUN_ID}/artifacts/a.fft", "/etc/passwd"],
            backend=backend, settings=settings,
        )


def test_stacksearch_rejects_non_fft(settings: Settings) -> None:
    (settings.runs_dir / PRIOR_RUN_ID / "artifacts" / "c.dat").write_bytes(b"D")
    backend = FakeDockerBackend()
    with pytest.raises(PathSecurityError, match=".fft"):
        run_stacksearch(
            [f"{PRIOR_RUN_ID}/artifacts/a.fft", f"{PRIOR_RUN_ID}/artifacts/c.dat"],
            backend=backend, settings=settings,
        )
