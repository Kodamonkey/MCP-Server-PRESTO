"""Unit tests for the runs/ index writer."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from presto_mcp.manifest import write_manifest
from presto_mcp.models import RunManifest, RunStatus
from presto_mcp.path_security import create_run_dir
from presto_mcp.run_index import INDEX_JSON, INDEX_MD, write_run_index


def _make_run(runs_root: Path, tool: str, input_file: str | None) -> str:
    run_id, run_dir = create_run_dir(tool, runs_root)
    inputs = {"input_file": input_file} if input_file else {}
    label = None
    if input_file:
        from presto_mcp.run_label import run_label

        label = run_label(tool, inputs)
    m = RunManifest(
        run_id=run_id,
        tool=tool,
        status=RunStatus.SUCCESS,
        exit_code=0,
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
        duration_s=1.5,
        timeout_s=1800,
        image="img:tag",
        docker_argv=["docker", "run"],
        presto_argv=[tool],
        inputs=inputs,
        container_inputs={},
        cpus=2.0,
        memory_mb=1024,
        label=label,
        artifacts=[],
    )
    write_manifest(run_dir, m)
    return run_id


def test_write_run_index_creates_md_and_json(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    runs.mkdir()
    _make_run(runs, "rfifind", "J0532+3305.fil")
    _make_run(runs, "prepdata", "J0532+3305.fil")
    _make_run(runs, "ddplan", None)

    write_run_index(runs)

    md = (runs / INDEX_MD).read_text(encoding="utf-8")
    assert "# Runs index" in md
    assert "J0532+3305__rfifind" in md
    assert "## By observation" in md
    assert "### J0532+3305" in md  # grouped by observation basename
    assert "### (no input)" in md  # ddplan has no input

    data = json.loads((runs / INDEX_JSON).read_text(encoding="utf-8"))
    assert data["count"] == 3
    tools = {r["tool"] for r in data["runs"]}
    assert tools == {"rfifind", "prepdata", "ddplan"}
    # input_file + label surfaced on the machine view
    rfi = next(r for r in data["runs"] if r["tool"] == "rfifind")
    assert rfi["input_file"] == "J0532+3305.fil"
    assert rfi["label"] == "J0532+3305__rfifind"


def test_write_run_index_empty_dir_is_safe(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    runs.mkdir()
    write_run_index(runs)
    assert "no runs yet" in (runs / INDEX_MD).read_text(encoding="utf-8")


def test_write_run_index_missing_dir_noop(tmp_path: Path) -> None:
    # Must not raise when the runs dir does not exist.
    write_run_index(tmp_path / "does_not_exist")
