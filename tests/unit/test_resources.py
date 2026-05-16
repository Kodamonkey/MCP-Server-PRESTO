"""Tests for the MCP resource handlers."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from presto_mcp.config import Settings
from presto_mcp.errors import PathSecurityError
from presto_mcp.manifest import write_manifest
from presto_mcp.models import RunManifest, RunStatus
from presto_mcp.resources import (
    LARGE_ARTIFACT_BYTES,
    read_artifact_resource,
    read_log_resource,
    read_manifest_resource,
)


@pytest.fixture
def settings_with_run(tmp_path: Path) -> tuple[Settings, str]:
    runs = tmp_path / "runs"
    runs.mkdir()
    run_id = "20260516T143052Z-K7QM3A"
    rd = runs / run_id
    (rd / "artifacts").mkdir(parents=True)
    (rd / "stdout.log").write_text("hello stdout\n", encoding="utf-8")
    (rd / "stderr.log").write_text("hello stderr\n", encoding="utf-8")
    (rd / "artifacts" / "foo.txt").write_text("small artifact\n", encoding="utf-8")
    (rd / "artifacts" / "big.bin").write_bytes(b"\x00" * (LARGE_ARTIFACT_BYTES + 1))

    manifest = RunManifest(
        run_id=run_id,
        tool="readfile",
        status=RunStatus.SUCCESS,
        exit_code=0,
        started_at=datetime(2026, 5, 16, 14, 30, 52, tzinfo=UTC),
        finished_at=datetime(2026, 5, 16, 14, 30, 54, tzinfo=UTC),
        duration_s=1.0,
        timeout_s=60,
        image="alex88ridolfi/presto5:png",
        docker_argv=["docker", "run"],
        presto_argv=["readfile", "/data/x.fil"],
        cpus=2.0,
        memory_mb=1024,
        artifacts=["foo.txt", "big.bin"],
    )
    write_manifest(rd, manifest)

    s = Settings(
        image="alex88ridolfi/presto5:png",
        data_dir=tmp_path / "data",
        runs_dir=runs.resolve(),
        outputs_dir=tmp_path / "outputs",
        logs_dir=tmp_path / "logs",
        default_cpus=2.0,
        default_memory_mb=1024,
        default_timeout_s=60,
        network="none",
        skip_healthcheck=True,
    )
    return s, run_id


def test_read_manifest(settings_with_run: tuple[Settings, str]) -> None:
    s, run_id = settings_with_run
    body = read_manifest_resource(s, run_id)
    payload = json.loads(body)
    assert payload["run_id"] == run_id
    assert payload["tool"] == "readfile"


def test_read_stdout_stderr(settings_with_run: tuple[Settings, str]) -> None:
    s, run_id = settings_with_run
    assert read_log_resource(s, run_id, "stdout") == "hello stdout\n"
    assert read_log_resource(s, run_id, "stderr") == "hello stderr\n"


def test_read_log_invalid_stream(settings_with_run: tuple[Settings, str]) -> None:
    s, run_id = settings_with_run
    with pytest.raises(PathSecurityError, match="must be 'stdout' or 'stderr'"):
        read_log_resource(s, run_id, "trace")


def test_read_small_artifact(settings_with_run: tuple[Settings, str]) -> None:
    s, run_id = settings_with_run
    body, mime = read_artifact_resource(s, run_id, "foo.txt")
    assert body == "small artifact\n"
    assert mime.startswith("text/")


def test_large_artifact_returns_descriptor(settings_with_run: tuple[Settings, str]) -> None:
    s, run_id = settings_with_run
    body, mime = read_artifact_resource(s, run_id, "big.bin")
    payload = json.loads(body)
    assert payload["kind"] == "artifact-metadata"
    assert payload["name"] == "big.bin"
    assert payload["size_bytes"] > LARGE_ARTIFACT_BYTES
    assert mime == "application/json"


def test_artifact_traversal_rejected(settings_with_run: tuple[Settings, str]) -> None:
    s, run_id = settings_with_run
    with pytest.raises(PathSecurityError):
        read_artifact_resource(s, run_id, "../stdout.log")
    with pytest.raises(PathSecurityError):
        read_artifact_resource(s, run_id, "sub/foo.txt")
    with pytest.raises(PathSecurityError):
        read_artifact_resource(s, run_id, "..")
    with pytest.raises(PathSecurityError):
        read_artifact_resource(s, run_id, "")


def test_invalid_run_id_rejected(settings_with_run: tuple[Settings, str]) -> None:
    s, _ = settings_with_run
    with pytest.raises(PathSecurityError, match="invalid run_id"):
        read_manifest_resource(s, "../../etc/passwd")
    with pytest.raises(PathSecurityError, match="invalid run_id"):
        read_log_resource(s, "not-an-id", "stdout")


def test_missing_run_rejected(settings_with_run: tuple[Settings, str]) -> None:
    s, _ = settings_with_run
    with pytest.raises(PathSecurityError, match="run does not exist"):
        read_manifest_resource(s, "20260101T000000Z-AAAAAA")
