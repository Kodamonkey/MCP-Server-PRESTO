"""Integration test for make_spd with FakeDockerBackend."""

from __future__ import annotations

from pathlib import Path

import pytest

from presto_mcp.config import Settings
from presto_mcp.errors import PathSecurityError
from presto_mcp.manifest import load_manifest
from presto_mcp.models import RunStatus
from presto_mcp.tools.make_spd import run_make_spd
from tests.fakes.fake_docker_backend import FakeDockerBackend, FakeResponse

PRIOR_RUN_ID = "20260517T120000Z-MMMMMM"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    data = tmp_path / "data"
    data.mkdir()
    (data / "raw.fil").write_bytes(b"FIL" * 64)
    (data / "rfi.mask").write_bytes(b"M" * 16)

    runs = tmp_path / "runs"
    prior = runs / PRIOR_RUN_ID / "artifacts"
    prior.mkdir(parents=True)
    (prior / "groups.txt").write_text("Group 1\n", encoding="utf-8")
    for dm in ("0.00",):
        (prior / f"sub_DM{dm}.singlepulse").write_bytes(b"# x\n1 2 3 4 5\n")

    return Settings(
        image="alex88ridolfi/presto5:png",
        data_dir=data.resolve(),
        runs_dir=runs.resolve(),
        outputs_dir=(tmp_path / "outputs").resolve(),
        default_cpus=2.0, default_memory_mb=1024, default_timeout_s=60,
        network="none", skip_healthcheck=True,
    )


def test_make_spd_argv_and_artifacts(settings: Settings) -> None:
    backend = FakeDockerBackend(
        responses={
            "make_spd.py": FakeResponse(
                stdout="ok\n",
                status=RunStatus.SUCCESS,
                artifacts={"spd_DM10.0_t12.3_RANK5.spd": b"NPZ"},
            )
        }
    )
    result = run_make_spd(
        "raw.fil",
        f"{PRIOR_RUN_ID}/artifacts/groups.txt",
        [f"{PRIOR_RUN_ID}/artifacts/sub_DM0.00.singlepulse"],
        backend=backend, settings=settings,
        mask_file="rfi.mask", apply_mask=True,
    )
    assert result.status == RunStatus.SUCCESS
    assert result.result is not None
    assert result.result.spd_files == ["spd_DM10.0_t12.3_RANK5.spd"]

    argv = backend.calls[0].invocation.argv
    assert "make_spd.py" in argv
    assert "--groupsfile" in argv and "groups.txt" in argv
    assert "--maskfile" in argv and "/data/rfi.mask" in argv
    assert "--mask" in argv
    assert "/data/raw.fil" in argv
    assert "sub_DM0.00.singlepulse" in argv
    assert "--workdir" in argv and "/outputs/artifacts" in argv

    run_dir = settings.runs_dir / result.run_id
    assert (run_dir / "artifacts" / "groups.txt").is_file()
    assert (run_dir / "artifacts" / "sub_DM0.00.singlepulse").is_file()

    m = load_manifest(run_dir)
    assert m.tool == "make_spd"


def test_make_spd_rejects_bad_groups(settings: Settings) -> None:
    backend = FakeDockerBackend()
    with pytest.raises(PathSecurityError):
        run_make_spd(
            "raw.fil",
            f"{PRIOR_RUN_ID}/artifacts/sub_DM0.00.singlepulse",
            [f"{PRIOR_RUN_ID}/artifacts/sub_DM0.00.singlepulse"],
            backend=backend, settings=settings,
        )
