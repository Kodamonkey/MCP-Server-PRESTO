"""Integration test for presto.pfdzap (experimental)."""

from __future__ import annotations

from pathlib import Path

import pytest

from presto_mcp.config import Settings
from presto_mcp.errors import PathSecurityError, PolicyViolationError
from presto_mcp.models import RunStatus
from presto_mcp.tools.pfdzap import run_pfdzap
from tests.fakes.fake_docker_backend import FakeDockerBackend, FakeResponse

PRIOR_RUN_ID = "20260517T120000Z-CCCCCC"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    data = tmp_path / "data"
    data.mkdir()
    runs = tmp_path / "runs"
    prior = runs / PRIOR_RUN_ID / "artifacts"
    prior.mkdir(parents=True)
    (prior / "fold.pfd").write_bytes(b"P" * 16)
    (prior / "fold.txt").write_text("not a pfd", encoding="utf-8")
    return Settings(
        image="alex88ridolfi/presto5:png",
        data_dir=data.resolve(),
        runs_dir=runs.resolve(),
        outputs_dir=(tmp_path / "outputs").resolve(),
        default_cpus=2.0, default_memory_mb=1024, default_timeout_s=60,
        network="none", skip_healthcheck=True,
    )


def test_pfdzap_writes_zap_file_and_argv(settings: Settings) -> None:
    backend = FakeDockerBackend(
        responses={
            "pfdzap.py": FakeResponse(
                stdout="ok\n",
                status=RunStatus.SUCCESS,
                artifacts={"pfdzap.pfd": b"Z"},  # zapped output
            )
        }
    )
    result = run_pfdzap(
        f"{PRIOR_RUN_ID}/artifacts/fold.pfd",
        backend=backend,
        zap_commands=["0:10", "60:80"],
        output_prefix="pfdzap",
        settings=settings,
    )
    assert result.status == RunStatus.SUCCESS
    assert result.result is not None
    assert result.result.output_pfd_file == "pfdzap.pfd"
    assert result.result.zap_commands_file == "pfdzap.zap"

    # Zap commands file actually written.
    zap_path = (
        settings.runs_dir / result.run_id / "artifacts" / "pfdzap.zap"
    )
    assert zap_path.read_text(encoding="utf-8") == "0:10\n60:80\n"

    argv = backend.calls[0].invocation.argv
    assert "pfdzap.py" in argv
    assert "pfdzap.zap" in argv
    assert "fold.pfd" in argv


def test_pfdzap_rejects_bad_commands(settings: Settings) -> None:
    backend = FakeDockerBackend()
    with pytest.raises(PolicyViolationError):
        run_pfdzap(
            f"{PRIOR_RUN_ID}/artifacts/fold.pfd",
            backend=backend,
            zap_commands=["rm -rf /"],
            settings=settings,
        )
    assert backend.calls == []


def test_pfdzap_requires_at_least_one_command(settings: Settings) -> None:
    backend = FakeDockerBackend()
    with pytest.raises(PolicyViolationError):
        run_pfdzap(
            f"{PRIOR_RUN_ID}/artifacts/fold.pfd",
            backend=backend,
            zap_commands=[],
            settings=settings,
        )
    assert backend.calls == []


def test_pfdzap_rejects_non_pfd(settings: Settings) -> None:
    backend = FakeDockerBackend()
    with pytest.raises(PathSecurityError, match=".pfd"):
        run_pfdzap(
            f"{PRIOR_RUN_ID}/artifacts/fold.txt",
            backend=backend,
            zap_commands=["0:1"],
            settings=settings,
        )
    assert backend.calls == []


def test_pfdzap_rejects_missing_pfd(settings: Settings) -> None:
    backend = FakeDockerBackend()
    with pytest.raises(PathSecurityError, match="does not exist"):
        run_pfdzap(
            f"{PRIOR_RUN_ID}/artifacts/missing.pfd",
            backend=backend,
            zap_commands=["0:1"],
            settings=settings,
        )
    assert backend.calls == []
