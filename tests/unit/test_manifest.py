"""Manifest read/write/list round-trip tests."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from presto_mcp.errors import ManifestError
from presto_mcp.manifest import (
    get_manifest,
    list_run_ids,
    list_run_summaries,
    load_manifest,
    write_manifest,
)
from presto_mcp.models import RunManifest, RunStatus


def _sample_manifest(run_id: str = "20260516T143052Z-K7QM3A") -> RunManifest:
    return RunManifest(
        run_id=run_id,
        tool="readfile",
        status=RunStatus.SUCCESS,
        exit_code=0,
        started_at=datetime(2026, 5, 16, 14, 30, 52, tzinfo=UTC),
        finished_at=datetime(2026, 5, 16, 14, 30, 54, tzinfo=UTC),
        duration_s=1.84,
        timeout_s=1800,
        image="alex88ridolfi/presto5:png",
        docker_argv=["docker", "run", "--rm"],
        presto_argv=["readfile", "/data/sample.fil"],
        inputs={"input_file": "/host/data/sample.fil"},
        container_inputs={"input_file": "/data/sample.fil"},
        cpus=4.0,
        memory_mb=8192,
        artifacts=[],
    )


def test_round_trip(tmp_path: Path) -> None:
    run_dir = tmp_path / "20260516T143052Z-K7QM3A"
    run_dir.mkdir()
    m = _sample_manifest()
    write_manifest(run_dir, m)
    assert (run_dir / "manifest.json").is_file()
    loaded = load_manifest(run_dir)
    assert loaded == m


def test_load_missing(tmp_path: Path) -> None:
    with pytest.raises(ManifestError, match="not found"):
        load_manifest(tmp_path)


def test_write_into_missing_dir(tmp_path: Path) -> None:
    with pytest.raises(ManifestError, match="run_dir does not exist"):
        write_manifest(tmp_path / "ghost", _sample_manifest())


def test_list_run_ids_orders_chronologically(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    runs.mkdir()
    ids = [
        "20260101T000000Z-AAAAAA",
        "20260516T143052Z-K7QM3A",
        "20260301T120000Z-BBBBBB",
    ]
    for rid in ids:
        d = runs / rid
        d.mkdir()
        write_manifest(d, _sample_manifest(run_id=rid))
    listed = list_run_ids(runs)
    assert listed == sorted(ids)


def test_list_run_ids_skips_non_run_dirs(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    runs.mkdir()
    (runs / "not-a-run").mkdir()
    (runs / "20260516T143052Z-K7QM3A").mkdir()
    write_manifest(runs / "20260516T143052Z-K7QM3A", _sample_manifest())
    assert list_run_ids(runs) == ["20260516T143052Z-K7QM3A"]


def test_list_run_summaries_newest_first_and_limit(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    runs.mkdir()
    ids = [
        "20260101T000000Z-AAAAAA",
        "20260516T143052Z-K7QM3A",
        "20260301T120000Z-BBBBBB",
    ]
    for rid in ids:
        d = runs / rid
        d.mkdir()
        write_manifest(d, _sample_manifest(run_id=rid))
    summaries = list_run_summaries(runs, limit=2)
    assert [s.run_id for s in summaries] == [
        "20260516T143052Z-K7QM3A",
        "20260301T120000Z-BBBBBB",
    ]
    assert all(s.manifest_uri.startswith("presto://runs/") for s in summaries)


def test_get_manifest_rejects_bad_id(tmp_path: Path) -> None:
    with pytest.raises(ManifestError, match="invalid run_id"):
        get_manifest(tmp_path, "../../etc/passwd")


def test_get_manifest_ok(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    runs.mkdir()
    rid = "20260516T143052Z-K7QM3A"
    d = runs / rid
    d.mkdir()
    m = _sample_manifest(run_id=rid)
    write_manifest(d, m)
    assert get_manifest(runs, rid) == m
