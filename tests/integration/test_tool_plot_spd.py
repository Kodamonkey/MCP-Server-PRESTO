"""Integration test for plot_spd with FakeDockerBackend."""

from __future__ import annotations

from pathlib import Path

import pytest

from presto_mcp.config import Settings
from presto_mcp.errors import PathSecurityError
from presto_mcp.manifest import load_manifest
from presto_mcp.models import RunStatus
from presto_mcp.tools.plot_spd import run_plot_spd
from tests.fakes.fake_docker_backend import FakeDockerBackend, FakeResponse

PRIOR_RUN_ID = "20260517T120000Z-PPPPPP"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    data = tmp_path / "data"
    data.mkdir()
    runs = tmp_path / "runs"
    prior = runs / PRIOR_RUN_ID / "artifacts"
    prior.mkdir(parents=True)
    (prior / "cand.spd").write_bytes(b"\x00" * 16)
    (prior / "sub_DM0.00.singlepulse").write_bytes(b"# x\n1 2 3 4 5\n")
    return Settings(
        image="alex88ridolfi/presto5:png",
        data_dir=data.resolve(),
        runs_dir=runs.resolve(),
        outputs_dir=(tmp_path / "outputs").resolve(),
        default_cpus=2.0, default_memory_mb=1024, default_timeout_s=60,
        network="none", skip_healthcheck=True,
    )


def test_plot_spd_argv_and_png(settings: Settings) -> None:
    backend = FakeDockerBackend(
        responses={
            "plot_spd.py": FakeResponse(
                stdout="plotted\n",
                status=RunStatus.SUCCESS,
                artifacts={"spdplot.png": b"\x89PNG"},
            )
        }
    )
    result = run_plot_spd(
        f"{PRIOR_RUN_ID}/artifacts/cand.spd",
        backend=backend, settings=settings,
        singlepulse_files=[f"{PRIOR_RUN_ID}/artifacts/sub_DM0.00.singlepulse"],
    )
    assert result.status == RunStatus.SUCCESS
    assert result.result is not None
    assert result.result.png_file == "spdplot.png"

    argv = backend.calls[0].invocation.argv
    assert "plot_spd.py" in argv
    assert "-o" in argv and "spdplot" in argv
    assert "cand.spd" in argv
    assert "sub_DM0.00.singlepulse" in argv
    assert "--workdir" in argv and "/outputs/artifacts" in argv

    run_dir = settings.runs_dir / result.run_id
    assert (run_dir / "artifacts" / "cand.spd").is_file()
    m = load_manifest(run_dir)
    assert m.tool == "plot_spd"


def test_plot_spd_rejects_non_spd(settings: Settings) -> None:
    backend = FakeDockerBackend()
    with pytest.raises(PathSecurityError, match=".spd"):
        run_plot_spd(
            f"{PRIOR_RUN_ID}/artifacts/sub_DM0.00.singlepulse",
            backend=backend, settings=settings,
        )
