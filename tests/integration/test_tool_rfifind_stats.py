"""Integration test for presto.rfifind_stats with FakeDockerBackend."""

from __future__ import annotations

from pathlib import Path

import pytest

from presto_mcp.config import Settings
from presto_mcp.errors import PathSecurityError
from presto_mcp.models import RunStatus
from presto_mcp.tools.rfifind_stats import run_rfifind_stats
from tests.fakes.fake_docker_backend import FakeDockerBackend, FakeResponse

PRIOR_RUN_ID = "20260517T120000Z-AAAAAA"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    data = tmp_path / "data"
    data.mkdir()
    runs = tmp_path / "runs"
    prior = runs / PRIOR_RUN_ID / "artifacts"
    prior.mkdir(parents=True)
    (prior / "rfi.stats").write_bytes(b"s")
    (prior / "rfi.inf").write_text(" Data file name without suffix          =  rfi\n", encoding="utf-8")
    (prior / "rfi.mask").write_bytes(b"m")
    return Settings(
        image="alex88ridolfi/presto5:png",
        data_dir=data.resolve(),
        runs_dir=runs.resolve(),
        outputs_dir=(tmp_path / "outputs").resolve(),
        default_cpus=2.0, default_memory_mb=1024, default_timeout_s=60,
        network="none", skip_healthcheck=True,
    )


_STDOUT = """\
Loading rfifind output...
Bad channels: 0-31, 64, 96:99
Bad intervals: 12, 45-47
Done.
"""


def test_rfifind_stats_parses_summary(settings: Settings) -> None:
    backend = FakeDockerBackend(
        responses={
            "rfifind_stats.py": FakeResponse(stdout=_STDOUT, status=RunStatus.SUCCESS)
        }
    )
    result = run_rfifind_stats(
        f"{PRIOR_RUN_ID}/artifacts/rfi.stats",
        backend=backend,
        mask_file=f"{PRIOR_RUN_ID}/artifacts/rfi.mask",
        settings=settings,
    )
    assert result.status == RunStatus.SUCCESS
    assert result.result is not None
    # 0-31 → 32 channels, plus 64, plus 96..99 → 32 + 1 + 4 = 37
    assert len(result.result.bad_channels) == 37
    assert 64 in result.result.bad_channels
    assert {12, 45, 46, 47}.issubset(set(result.result.bad_intervals))

    argv = backend.calls[0].invocation.argv
    assert "rfifind_stats.py" in argv
    assert "/outputs/artifacts/rfi.stats" in argv
    # PRESTO rfifind_stats.py accepts only a single positional input.
    assert "/outputs/artifacts/rfi.mask" not in argv
    assert f"/runs/{PRIOR_RUN_ID}/artifacts/rfi.stats" not in argv
    assert "--workdir" in argv and "/outputs/artifacts" in argv
    run_dir = settings.runs_dir / result.run_id
    assert (run_dir / "artifacts" / "rfi.inf").is_file()


def test_rfifind_stats_rejects_bad_run_id(settings: Settings) -> None:
    backend = FakeDockerBackend()
    with pytest.raises(PathSecurityError):
        run_rfifind_stats(
            "../escape/artifacts/rfi.stats",
            backend=backend,
            settings=settings,
        )
    assert backend.calls == []
