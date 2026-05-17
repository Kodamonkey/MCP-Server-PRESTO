"""Integration test for presto.fb_truncate with FakeDockerBackend."""

from __future__ import annotations

from pathlib import Path

import pytest

from presto_mcp.config import Settings
from presto_mcp.errors import PolicyViolationError
from presto_mcp.models import RunStatus
from presto_mcp.tools.fb_truncate import run_fb_truncate
from tests.fakes.fake_docker_backend import FakeDockerBackend, FakeResponse


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    data = tmp_path / "data"
    data.mkdir()
    (data / "big.fil").write_bytes(b"\x00" * 64)
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


def test_fb_truncate_success(settings: Settings) -> None:
    backend = FakeDockerBackend(
        responses={
            "fb_truncate.py": FakeResponse(
                stdout="wrote /outputs/artifacts/trunc.fil\n",
                status=RunStatus.SUCCESS,
                artifacts={"trunc.fil": b"\x01" * 16},
            )
        }
    )
    result = run_fb_truncate(
        "big.fil",
        backend=backend,
        start_sample=100,
        num_samples=4096,
        output_prefix="trunc",
        settings=settings,
    )
    assert result.status == RunStatus.SUCCESS
    assert result.result is not None
    assert result.result.output_file == "trunc.fil"
    assert result.result.start_sample == 100
    assert result.result.num_samples == 4096

    argv = backend.calls[0].invocation.argv
    assert "fb_truncate.py" in argv
    assert "-s" in argv and "100" in argv
    assert "-n" in argv and "4096" in argv
    assert "/outputs/artifacts/trunc" in argv
    assert "/data/big.fil" in argv


def test_fb_truncate_rejects_negative_samples(settings: Settings) -> None:
    backend = FakeDockerBackend()
    with pytest.raises(PolicyViolationError):
        run_fb_truncate(
            "big.fil",
            backend=backend,
            start_sample=-1,
            num_samples=100,
            settings=settings,
        )
    assert backend.calls == []


def test_fb_truncate_rejects_zero_num_samples(settings: Settings) -> None:
    backend = FakeDockerBackend()
    with pytest.raises(PolicyViolationError):
        run_fb_truncate(
            "big.fil", backend=backend, num_samples=0, settings=settings
        )
    assert backend.calls == []
