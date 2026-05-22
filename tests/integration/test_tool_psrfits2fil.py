"""Integration test for presto.psrfits2fil with FakeDockerBackend."""

from __future__ import annotations

from pathlib import Path

import pytest

from presto_mcp.config import Settings
from presto_mcp.errors import PathSecurityError, PolicyViolationError
from presto_mcp.manifest import load_manifest
from presto_mcp.models import RunStatus
from presto_mcp.tools.psrfits2fil import run_psrfits2fil
from tests.fakes.fake_docker_backend import FakeDockerBackend, FakeResponse


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    data = tmp_path / "data"
    data.mkdir()
    (data / "obs.fits").write_bytes(b"\x00" * 16)
    return Settings(
        image="alex88ridolfi/presto5:png",
        data_dir=data.resolve(),
        runs_dir=(tmp_path / "runs").resolve(),
        outputs_dir=(tmp_path / "outputs").resolve(),
        default_cpus=2.0,
        default_memory_mb=1024,
        default_timeout_s=60,
        network="none",
        skip_healthcheck=True,
    )


def test_psrfits2fil_success(settings: Settings) -> None:
    backend = FakeDockerBackend(
        responses={
            "psrfits2fil.py": FakeResponse(
                stdout="Wrote /outputs/artifacts/fil.fil\n",
                status=RunStatus.SUCCESS,
                artifacts={"fil.fil": b"\x00\x00", "fil.inf": b"hdr"},
            )
        }
    )
    result = run_psrfits2fil(
        "obs.fits", backend=backend, output_prefix="fil", settings=settings
    )
    assert result.status == RunStatus.SUCCESS
    assert result.result is not None
    assert result.result.fil_files == ["fil.fil"]
    assert result.result.inf_files == ["fil.inf"]

    argv = backend.calls[0].invocation.argv
    assert "psrfits2fil.py" in argv
    assert "/data/obs.fits" in argv
    assert "/outputs/artifacts/fil" in argv

    m = load_manifest(settings.runs_dir / result.run_id)
    assert m.tool == "psrfits2fil"
    assert m.status == RunStatus.SUCCESS


def test_psrfits2fil_rejects_bad_prefix(settings: Settings) -> None:
    backend = FakeDockerBackend()
    with pytest.raises(PolicyViolationError):
        run_psrfits2fil(
            "obs.fits", backend=backend, output_prefix="../escape", settings=settings
        )
    assert backend.calls == []


def test_psrfits2fil_rejects_path_traversal(settings: Settings) -> None:
    backend = FakeDockerBackend()
    with pytest.raises(PathSecurityError):
        run_psrfits2fil("../escape.fits", backend=backend, settings=settings)
    assert backend.calls == []
