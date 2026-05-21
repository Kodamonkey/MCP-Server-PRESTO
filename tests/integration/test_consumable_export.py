"""Integration: executor path exports consumables after a successful tool run."""

from __future__ import annotations

from pathlib import Path

import pytest

from presto_mcp.config import Settings, set_resolved_container_python
from presto_mcp.models import RunStatus
from presto_mcp.tools.waterfaller import run_waterfaller
from tests.fakes.fake_docker_backend import FakeDockerBackend, FakeResponse


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    data = tmp_path / "data"
    data.mkdir()
    (data / "raw.fil").write_bytes(b"FIL" * 64)
    runs = tmp_path / "runs"
    runs.mkdir()
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    return Settings(
        image="alex88ridolfi/presto5:png",
        data_dir=data.resolve(),
        runs_dir=runs.resolve(),
        outputs_dir=outputs.resolve(),
        logs_dir=(tmp_path / "logs").resolve(),
        default_cpus=2.0,
        default_memory_mb=1024,
        default_timeout_s=60,
        network="none",
        skip_healthcheck=True,
        export_consumables=True,
    )


def test_waterfaller_exports_png_to_outputs(settings: Settings) -> None:
    set_resolved_container_python("python3")
    backend = FakeDockerBackend(
        responses={
            "python3": FakeResponse(
                stdout="ok\n",
                status=RunStatus.SUCCESS,
                artifacts={"waterfall.png": b"\x89PNG"},
            )
        }
    )
    result = run_waterfaller(
        "raw.fil",
        backend=backend,
        settings=settings,
        start_s=1.0,
        duration_s=0.1,
        dm=10.0,
        colour_map="inferno",
    )
    assert result.status == RunStatus.SUCCESS

    exported = settings.outputs_dir / "final" / f"{result.run_id}_waterfaller_waterfall.png"
    assert exported.is_file()
    assert (settings.outputs_dir / "index.jsonl").is_file()
