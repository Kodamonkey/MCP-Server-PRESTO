"""Integration test for the readfile tool using FakeDockerBackend.

Feeds the canned real-PRESTO stdout fixture into the executor and asserts the
returned ``ToolRunResult[ReadfileMetadata]`` is properly shaped.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from presto_mcp.config import Settings
from presto_mcp.manifest import load_manifest
from presto_mcp.models import RunStatus
from presto_mcp.tools.readfile import run_readfile
from tests.fakes.fake_docker_backend import FakeDockerBackend, FakeResponse


@pytest.fixture
def settings_and_data(tmp_path: Path) -> Settings:
    data = tmp_path / "data"
    data.mkdir()
    (data / "input.fil").write_bytes(b"\x00" * 16)
    return Settings(
        image="alex88ridolfi/presto5:png",
        data_dir=data.resolve(),
        runs_dir=(tmp_path / "runs").resolve(),
        outputs_dir=(tmp_path / "outputs").resolve(),
        logs_dir=(tmp_path / "logs").resolve(),
        default_cpus=2.0,
        default_memory_mb=1024,
        default_timeout_s=60,
        network="none",
        skip_healthcheck=True,
    )


def test_run_readfile_with_real_fixture(
    settings_and_data: Settings,
    stdout_fixture_dir: Path,
) -> None:
    fixture = (stdout_fixture_dir / "readfile_J0532+3305.txt").read_text(encoding="utf-8-sig")
    backend = FakeDockerBackend(
        responses={"readfile": FakeResponse(stdout=fixture, status=RunStatus.SUCCESS)}
    )
    result = run_readfile("input.fil", backend=backend, settings=settings_and_data)

    assert result.status == RunStatus.SUCCESS
    assert result.result is not None
    assert result.result.source_name == "J0532+3305"
    assert result.result.num_channels == 672
    assert result.result.central_freq_mhz == pytest.approx(1564.25)

    # The executor produced one docker invocation with the expected argv tail.
    assert len(backend.calls) == 1
    argv = backend.calls[0].invocation.argv
    assert argv[-2:] == ["readfile", "/data/input.fil"]
    assert "--network=none" in argv

    m = load_manifest(settings_and_data.runs_dir / result.run_id)
    assert m.tool == "readfile"
    assert m.status == RunStatus.SUCCESS
    assert m.presto_argv == ["readfile", "/data/input.fil"]


def test_run_readfile_rejects_outside_data(settings_and_data: Settings) -> None:
    backend = FakeDockerBackend()
    from presto_mcp.errors import PathSecurityError

    with pytest.raises(PathSecurityError):
        run_readfile("../escape.fil", backend=backend, settings=settings_and_data)
    # Backend must never have been called for an invalid path.
    assert backend.calls == []
