"""Integration test for rfifind tool using FakeDockerBackend."""

from __future__ import annotations

from pathlib import Path

import pytest

from presto_mcp.config import Settings
from presto_mcp.errors import PolicyViolationError
from presto_mcp.manifest import load_manifest
from presto_mcp.models import RunStatus
from presto_mcp.tools.rfifind import run_rfifind
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
        default_cpus=2.0,
        default_memory_mb=1024,
        default_timeout_s=60,
        network="none",
        skip_healthcheck=True,
    )


def test_rfifind_argv_and_artifacts(
    settings: Settings, stdout_fixture_dir: Path
) -> None:
    text = (stdout_fixture_dir / "rfifind_J0532+3305.txt").read_text(encoding="utf-8-sig")
    backend = FakeDockerBackend(
        responses={
            "rfifind": FakeResponse(
                stdout=text,
                status=RunStatus.SUCCESS,
                artifacts={
                    "rfi_rfifind.mask": b"M",
                    "rfi_rfifind.rfi": b"R",
                    "rfi_rfifind.stats": b"S",
                    "rfi_rfifind.ps": b"P",
                },
            )
        }
    )

    result = run_rfifind("input.fil", backend=backend, time=2.0, settings=settings)

    assert result.status == RunStatus.SUCCESS
    assert result.result is not None
    assert result.result.num_intervals == 22176
    assert result.result.rfi_instances == 1323
    assert set(Path(uri).name for uri in result.artifact_uris) == {
        "rfi_rfifind.mask",
        "rfi_rfifind.rfi",
        "rfi_rfifind.stats",
        "rfi_rfifind.ps",
    }

    argv = backend.calls[0].invocation.argv
    assert argv[-5:] == [
        "rfifind", "-time", "2.0", "-o", "/outputs/artifacts/rfi",
    ] or argv[-6:-1] == ["rfifind", "-time", "2.0", "-o", "/outputs/artifacts/rfi"]
    # The container input path is the last arg.
    assert argv[-1] == "/data/input.fil"

    m = load_manifest(settings.runs_dir / result.run_id)
    assert m.tool == "rfifind"
    assert "rfifind" in m.presto_argv
    assert "/outputs/artifacts/rfi" in m.presto_argv


def test_rfifind_rejects_bad_time(settings: Settings) -> None:
    backend = FakeDockerBackend()
    with pytest.raises(PolicyViolationError):
        run_rfifind("input.fil", backend=backend, time=0.0, settings=settings)
    with pytest.raises(PolicyViolationError):
        run_rfifind("input.fil", backend=backend, time=10_000.0, settings=settings)
    assert backend.calls == []


def test_rfifind_rejects_bad_prefix(settings: Settings) -> None:
    backend = FakeDockerBackend()
    with pytest.raises(PolicyViolationError):
        run_rfifind("input.fil", backend=backend, output_prefix="../escape", settings=settings)
    with pytest.raises(PolicyViolationError):
        run_rfifind("input.fil", backend=backend, output_prefix="bad name", settings=settings)
    assert backend.calls == []


def test_rfifind_default_prefix(settings: Settings) -> None:
    backend = FakeDockerBackend(
        responses={"rfifind": FakeResponse(stdout="Pulsar...\n", status=RunStatus.SUCCESS)}
    )
    run_rfifind("input.fil", backend=backend, settings=settings)
    argv = backend.calls[0].invocation.argv
    assert "/outputs/artifacts/rfi" in argv
