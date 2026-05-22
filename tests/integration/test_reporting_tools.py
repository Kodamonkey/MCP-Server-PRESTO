"""Integration tests for the 7 reporting MCP tools + intention routing."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from presto_mcp.config import get_settings
from presto_mcp.tools.reporting import (
    run_export_candidates_csv,
    run_generate_modern_report_bundle,
    run_generate_report_html,
    run_generate_report_markdown,
    run_generate_summary_json,
    run_generate_visual_artifacts,
)

_RID = "20260101T000000Z-ABC234"
_SP = "# DM Sigma Time Sample Downfact\n42.0 9.1 12.3 100000 2\n0.3 6.0 3.2 9000 1\n"


@pytest.fixture
def synthetic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PRESTO_MCP_LOG_DIR", str(tmp_path / "logs"))
    runs, outs, data = tmp_path / "runs", tmp_path / "outputs", tmp_path / "data"
    for d in (runs, outs, data):
        d.mkdir()
    art = runs / _RID / "artifacts"
    art.mkdir(parents=True)
    (art / "obs.singlepulse").write_text(_SP, encoding="utf-8")
    (runs / _RID / "manifest.json").write_text(
        json.dumps(
            {
                "tool": "single_pulse_search",
                "status": "SUCCESS",
                "duration_s": 5.0,
                "exit_code": 0,
                "inputs": {"input_file": "obs.fil"},
                "stdout_path": "stdout.log",
            }
        ),
        encoding="utf-8",
    )
    (runs / _RID / "stdout.log").write_text("", encoding="utf-8")
    return get_settings().with_overrides(runs_dir=runs, outputs_dir=outs, data_dir=data)


def test_export_candidates_csv(synthetic) -> None:
    result = run_export_candidates_csv(run_ids=[_RID], settings=synthetic)
    out = Path(result.output_dir)
    assert (out / "candidates.csv").is_file()
    assert result.candidate_count == 2
    # candidate-only export: no visuals / report
    assert not (out / "report.html").exists()


def test_summary_json_only(synthetic) -> None:
    result = run_generate_summary_json(run_ids=[_RID], settings=synthetic)
    out = Path(result.output_dir)
    assert (out / "summary.json").is_file()
    assert not (out / "candidates.csv").exists()
    data = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert data["candidate_counts"]["total"] == 2


def test_metadata_prompt_creates_no_visuals(synthetic) -> None:
    result = run_generate_modern_report_bundle(
        run_ids=[_RID], settings=synthetic, wants_metadata_only=True
    )
    out = Path(result.output_dir)
    assert (out / "summary.json").is_file()
    assert not (out / "report.html").exists()
    assert not any((out / "visuals").iterdir())


def test_visual_inspection_creates_png_and_html(synthetic) -> None:
    Image.new("RGB", (16, 16), "white").save(
        synthetic.runs_dir / _RID / "artifacts" / "diagnostic.png"
    )
    result = run_generate_modern_report_bundle(
        run_ids=[_RID], settings=synthetic, wants_visuals=True
    )
    out = Path(result.output_dir)
    assert (out / "visuals" / "diagnostic.png").is_file()
    assert (out / "report.html").is_file()


def test_full_modern_report_bundle(synthetic) -> None:
    result = run_generate_modern_report_bundle(
        run_ids=[_RID], settings=synthetic, wants_report=True
    )
    out = Path(result.output_dir)
    for name in ("summary.json", "candidates.csv", "report.html", "report.md", "manifest.json"):
        assert (out / name).is_file(), name
    # observability artifacts mirrored into the bundle
    assert (out / "status.md").is_file()
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status_md"] == "status.md"
    assert manifest["log_paths"]


def test_no_extra_files_limits_output(synthetic) -> None:
    result = run_generate_modern_report_bundle(
        run_ids=[_RID], settings=synthetic, wants_no_extra_files=True
    )
    out = Path(result.output_dir)
    assert not (out / "summary.json").exists()
    assert not (out / "candidates.csv").exists()
    assert not (out / "report.html").exists()
    # the manifest is always written (audit record)
    assert (out / "manifest.json").is_file()


def test_html_report_offline(synthetic) -> None:
    result = run_generate_report_html(run_ids=[_RID], settings=synthetic)
    html = (Path(result.output_dir) / "report.html").read_text(encoding="utf-8")
    assert "https://" not in html
    assert "candidates.csv" in html


def test_markdown_report(synthetic) -> None:
    result = run_generate_report_markdown(run_ids=[_RID], settings=synthetic)
    md = (Path(result.output_dir) / "report.md").read_text(encoding="utf-8")
    assert "# " in md
    assert "Candidate Summary" in md


def test_visual_artifacts_tool(synthetic) -> None:
    Image.new("RGB", (16, 16), "white").save(
        synthetic.runs_dir / _RID / "artifacts" / "plot.png"
    )
    result = run_generate_visual_artifacts(run_ids=[_RID], settings=synthetic)
    out = Path(result.output_dir)
    assert (out / "visuals" / "plot.png").is_file()
    assert (out / "thumbnails" / "plot.png").is_file()


def test_raw_presto_outputs_not_published_by_default(synthetic) -> None:
    # a raw .dat sits in the run dir; it must not reach the public tree
    (synthetic.runs_dir / _RID / "artifacts" / "obs.dat").write_bytes(b"raw")
    result = run_generate_modern_report_bundle(
        run_ids=[_RID], settings=synthetic, wants_report=True
    )
    out = Path(result.output_dir)
    assert not any(p.suffix == ".dat" for p in out.rglob("*"))
    assert not (out / "presto_raw_exports").exists()
