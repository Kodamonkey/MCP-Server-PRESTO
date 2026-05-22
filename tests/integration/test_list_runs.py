"""Integration test for list_runs / get_run_manifest reflection tools."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from presto_mcp.config import Settings
from presto_mcp.errors import ManifestError
from presto_mcp.manifest import write_manifest
from presto_mcp.models import RunManifest, RunStatus
from presto_mcp.tools import list_runs as list_runs_tool


@pytest.fixture
def populated_runs(tmp_path: Path) -> Settings:
    runs = tmp_path / "runs"
    runs.mkdir()
    for rid in [
        "20260101T000000Z-AAAAAA",
        "20260516T143052Z-K7QM3A",
        "20260301T120000Z-BBBBBB",
    ]:
        rd = runs / rid
        rd.mkdir()
        m = RunManifest(
            run_id=rid,
            tool="readfile",
            status=RunStatus.SUCCESS,
            exit_code=0,
            started_at=datetime(2026, 1, 1, tzinfo=UTC),
            finished_at=datetime(2026, 1, 1, tzinfo=UTC),
            duration_s=0.5,
            timeout_s=60,
            image="i:t",
            docker_argv=[],
            presto_argv=[],
            cpus=1.0,
            memory_mb=512,
        )
        write_manifest(rd, m)
    return Settings(
        image="i:t",
        data_dir=tmp_path / "data",
        runs_dir=runs.resolve(),
        outputs_dir=tmp_path / "outputs",
        default_cpus=1.0,
        default_memory_mb=512,
        default_timeout_s=60,
        network="none",
        skip_healthcheck=True,
    )


def test_list_runs_newest_first(populated_runs: Settings) -> None:
    summaries = list_runs_tool.list_runs(settings=populated_runs, limit=10)
    assert [s.run_id for s in summaries] == [
        "20260516T143052Z-K7QM3A",
        "20260301T120000Z-BBBBBB",
        "20260101T000000Z-AAAAAA",
    ]
    for s in summaries:
        assert s.manifest_uri.startswith("presto://runs/")
        assert s.tool == "readfile"
        assert s.status == RunStatus.SUCCESS


def test_list_runs_limit(populated_runs: Settings) -> None:
    summaries = list_runs_tool.list_runs(settings=populated_runs, limit=2)
    assert len(summaries) == 2
    assert summaries[0].run_id == "20260516T143052Z-K7QM3A"


def test_get_run_manifest_ok(populated_runs: Settings) -> None:
    m = list_runs_tool.get_run_manifest(
        "20260516T143052Z-K7QM3A", settings=populated_runs
    )
    assert m.run_id == "20260516T143052Z-K7QM3A"


def test_get_run_manifest_bad_id(populated_runs: Settings) -> None:
    with pytest.raises(ManifestError, match="invalid run_id"):
        list_runs_tool.get_run_manifest("bogus", settings=populated_runs)
