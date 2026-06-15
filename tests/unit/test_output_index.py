"""Unit tests for the outputs/ bundle index + latest pointers."""

from __future__ import annotations

import json
from pathlib import Path

from presto_mcp.reporting.output_index import (
    INDEX_JSON,
    INDEX_MD,
    LATEST_REPORT,
    LATEST_SUMMARY,
    write_output_index,
)


def _make_bundle(
    outputs: Path, name: str, *, status: str = "success", candidates: int | None = None
) -> Path:
    d = outputs / name
    d.mkdir(parents=True)
    manifest = {"run_id": "20260531T010000Z-ABCDEF", "status": status, "report_html": "report.html"}
    (d / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (d / "report.html").write_text(f"<html>{name}</html>", encoding="utf-8")
    if candidates is not None:
        summary = {"candidate_counts": {"total": candidates}}
        (d / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
    return d


def test_write_output_index_and_latest(tmp_path: Path) -> None:
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    _make_bundle(outputs, "J0532+3305__20260531T010000Z", candidates=7)
    newest = _make_bundle(outputs, "J0532+3305__20260531T020000Z", candidates=3)

    write_output_index(outputs)

    md = (outputs / INDEX_MD).read_text(encoding="utf-8")
    assert "# Report bundles index" in md
    assert "J0532+3305__20260531T020000Z" in md

    data = json.loads((outputs / INDEX_JSON).read_text(encoding="utf-8"))
    assert data["count"] == 2
    # newest first
    assert data["bundles"][0]["bundle"] == "J0532+3305__20260531T020000Z"

    # latest pointers mirror the newest bundle
    assert (outputs / LATEST_REPORT).read_text(encoding="utf-8") == newest.joinpath(
        "report.html"
    ).read_text(encoding="utf-8")
    assert (outputs / LATEST_SUMMARY).is_file()


def test_index_ignores_reserved_and_non_bundles(tmp_path: Path) -> None:
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    _make_bundle(outputs, "obs__20260531T010000Z")
    (outputs / "loose_file.html").write_text("x", encoding="utf-8")
    (outputs / "no_manifest_dir").mkdir()

    write_output_index(outputs)
    data = json.loads((outputs / INDEX_JSON).read_text(encoding="utf-8"))
    assert data["count"] == 1


def test_empty_outputs_safe(tmp_path: Path) -> None:
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    write_output_index(outputs)
    assert "no bundles yet" in (outputs / INDEX_MD).read_text(encoding="utf-8")
