"""Tests for presto.summarize_run and presto.inspect_artifacts."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from presto_mcp.config import Settings
from presto_mcp.errors import PathSecurityError
from presto_mcp.manifest import write_manifest
from presto_mcp.models import ArtifactType, RunManifest, RunStatus
from presto_mcp.tools.summarize_run import inspect_artifacts, summarize_run


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        image="alex88ridolfi/presto5:png",
        data_dir=tmp_path / "data",
        runs_dir=(tmp_path / "runs").resolve(),
        outputs_dir=tmp_path / "outputs",
        logs_dir=tmp_path / "logs",
        default_cpus=2.0,
        default_memory_mb=1024,
        default_timeout_s=60,
        network="none",
        skip_healthcheck=True,
    )


def _build_run(tmp_path: Path) -> tuple[Settings, str]:
    s = _settings(tmp_path)
    s.runs_dir.mkdir(parents=True)
    run_id = "20260516T143052Z-K7QM3A"
    rd = s.runs_dir / run_id
    art = rd / "artifacts"
    art.mkdir(parents=True)
    (rd / "stdout.log").write_text("", encoding="utf-8")
    (rd / "stderr.log").write_text("", encoding="utf-8")
    for name in (
        "obs_rfifind.mask",
        "obs_DM12.34.dat",
        "obs_DM12.34.inf",
        "obs_DM12.34.fft",
        "obs_DM12.34_ACCEL_200",
        "obs_DM12.34.singlepulse",
        "fold.pfd",
        "fold.bestprof",
        "plot.png",
    ):
        (art / name).write_bytes(b"x")

    manifest = RunManifest(
        run_id=run_id,
        tool="rfifind",
        status=RunStatus.SUCCESS,
        exit_code=0,
        started_at=datetime(2026, 5, 16, 14, 30, 52, tzinfo=UTC),
        finished_at=datetime(2026, 5, 16, 14, 30, 55, tzinfo=UTC),
        duration_s=3.0,
        timeout_s=60,
        image=s.image,
        docker_argv=["docker", "run"],
        presto_argv=["rfifind"],
        inputs={"input_file": "obs.fil"},
        cpus=2.0,
        memory_mb=1024,
        artifacts=[
            "obs_rfifind.mask",
            "obs_DM12.34.dat",
            "obs_DM12.34.inf",
            "obs_DM12.34.fft",
            "obs_DM12.34_ACCEL_200",
            "obs_DM12.34.singlepulse",
            "fold.pfd",
            "fold.bestprof",
            "plot.png",
        ],
    )
    write_manifest(rd, manifest)
    return s, run_id


def test_summarize_groups_by_type(tmp_path: Path) -> None:
    s, run_id = _build_run(tmp_path)
    summary = summarize_run(run_id, settings=s)

    assert summary.run_id == run_id
    assert summary.tool == "rfifind"
    assert summary.status == RunStatus.SUCCESS
    assert summary.artifact_counts.get(ArtifactType.RFI) == 1
    assert summary.artifact_counts.get(ArtifactType.TIME_SERIES) == 2  # .dat + .inf
    assert summary.artifact_counts.get(ArtifactType.FFT) == 1
    assert summary.artifact_counts.get(ArtifactType.ACCEL_CANDIDATES) == 1
    assert summary.artifact_counts.get(ArtifactType.SINGLE_PULSE) == 1
    # .pfd → FOLD, .bestprof → FOLD (classified by .bestprof rule)
    assert summary.artifact_counts.get(ArtifactType.FOLD) == 2
    assert summary.artifact_counts.get(ArtifactType.PLOTS) == 1


def test_summarize_suggests_next_tools(tmp_path: Path) -> None:
    s, run_id = _build_run(tmp_path)
    summary = summarize_run(run_id, settings=s)
    s_set = set(summary.next_suggested_tools)
    assert {
        "presto.prepdata",
        "presto.single_pulse_search",
        "presto.realfft",
        "presto.accelsearch",
        "presto.sifting",
        "presto.prepfold",
        "presto.rrattrap",
        "presto.get_toas",
    } <= s_set


def test_summarize_invalid_run_id(tmp_path: Path) -> None:
    s = _settings(tmp_path)
    s.runs_dir.mkdir(parents=True, exist_ok=True)
    with pytest.raises(PathSecurityError):
        summarize_run("not-a-run-id", settings=s)


def test_inspect_artifacts_shape(tmp_path: Path) -> None:
    s, run_id = _build_run(tmp_path)
    res = inspect_artifacts(run_id, settings=s)
    assert res.run_id == run_id
    names = {a.name for a in res.artifacts}
    assert "obs_rfifind.mask" in names
    for a in res.artifacts:
        assert a.resource_uri == f"presto://runs/{run_id}/artifacts/{a.name}"
    # .inf and .bestprof and .singlepulse are inline-readable (small text exts).
    by_name = {a.name: a for a in res.artifacts}
    assert by_name["obs_DM12.34.inf"].is_inline_readable is True
    assert by_name["fold.bestprof"].is_inline_readable is True
    assert by_name["obs_DM12.34.singlepulse"].is_inline_readable is True
    # Binary-ish exts are not inline-readable.
    assert by_name["fold.pfd"].is_inline_readable is False
    assert by_name["plot.png"].is_inline_readable is False
