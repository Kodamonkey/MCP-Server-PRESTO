"""Navigation resources: presto://data, presto://runs, /summary, /artifacts."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from presto_mcp import server as srv
from presto_mcp.config import Settings
from presto_mcp.manifest import write_manifest
from presto_mcp.models import RunManifest, RunStatus


def _settings(tmp_path: Path) -> Settings:
    data = tmp_path / "data"
    data.mkdir()
    (data / "obs.fil").write_bytes(b"x" * 8)
    return Settings(
        image="alex88ridolfi/presto5:png",
        data_dir=data,
        runs_dir=(tmp_path / "runs").resolve(),
        outputs_dir=tmp_path / "outputs",
        logs_dir=tmp_path / "logs",
        default_cpus=2.0,
        default_memory_mb=1024,
        default_timeout_s=60,
        network="none",
        skip_healthcheck=True,
    )


def _make_run(s: Settings) -> str:
    s.runs_dir.mkdir(parents=True, exist_ok=True)
    run_id = "20260516T143052Z-K7QM3A"
    rd = s.runs_dir / run_id
    (rd / "artifacts").mkdir(parents=True)
    (rd / "stdout.log").write_text("", encoding="utf-8")
    (rd / "stderr.log").write_text("", encoding="utf-8")
    (rd / "artifacts" / "obs.mask").write_bytes(b"m")
    (rd / "artifacts" / "obs.dat").write_bytes(b"d")
    write_manifest(
        rd,
        RunManifest(
            run_id=run_id,
            tool="rfifind",
            status=RunStatus.SUCCESS,
            exit_code=0,
            started_at=datetime(2026, 5, 16, 14, 30, 52, tzinfo=UTC),
            finished_at=datetime(2026, 5, 16, 14, 30, 55, tzinfo=UTC),
            duration_s=3.0,
            timeout_s=60,
            image=s.image,
            docker_argv=["docker"],
            presto_argv=["rfifind"],
            cpus=2.0,
            memory_mb=1024,
            artifacts=["obs.mask", "obs.dat"],
        ),
    )
    return run_id


def test_data_resource_returns_json(tmp_path: Path) -> None:
    s = _settings(tmp_path)
    srv.set_settings(s)
    try:
        payload = srv._resource_data_index()
        data = json.loads(payload)
        assert "files" in data and "count" in data
        names = {f["relative_path"] for f in data["files"]}
        assert "obs.fil" in names
    finally:
        srv.set_settings(None)  # type: ignore[arg-type]


def test_runs_resource_returns_index(tmp_path: Path) -> None:
    s = _settings(tmp_path)
    run_id = _make_run(s)
    srv.set_settings(s)
    try:
        payload = srv._resource_runs_index()
        data = json.loads(payload)
        assert data["count"] >= 1
        assert any(r["run_id"] == run_id for r in data["runs"])
    finally:
        srv.set_settings(None)  # type: ignore[arg-type]


def test_run_summary_resource(tmp_path: Path) -> None:
    s = _settings(tmp_path)
    run_id = _make_run(s)
    srv.set_settings(s)
    try:
        payload = srv._resource_run_summary(run_id)
        data = json.loads(payload)
        assert data["run_id"] == run_id
        assert data["tool"] == "rfifind"
        assert "artifact_counts" in data
    finally:
        srv.set_settings(None)  # type: ignore[arg-type]


def test_run_artifacts_resource(tmp_path: Path) -> None:
    s = _settings(tmp_path)
    run_id = _make_run(s)
    srv.set_settings(s)
    try:
        payload = srv._resource_run_artifacts(run_id)
        data = json.loads(payload)
        assert data["run_id"] == run_id
        names = {a["name"] for a in data["artifacts"]}
        assert {"obs.mask", "obs.dat"} <= names
    finally:
        srv.set_settings(None)  # type: ignore[arg-type]
