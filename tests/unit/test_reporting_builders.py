"""Unit tests for the reporting builders (summary / visual / waterfall / html)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from PIL import Image

from presto_mcp.reporting.artifact_manager import ArtifactManager
from presto_mcp.reporting.html_report_builder import build_html
from presto_mcp.reporting.schemas import (
    ArtifactPolicy,
    Candidate,
    CandidateType,
    ReportManifest,
    ReportOptions,
)
from presto_mcp.reporting.summary_builder import build_summary
from presto_mcp.reporting.visual_builder import collect_visuals, find_ghostscript
from presto_mcp.reporting.waterfall_builder import generate_waterfalls

_RID = "20260101T000000Z-ABC234"


def _candidates() -> list[Candidate]:
    return [
        Candidate(
            candidate_id=f"sp-{i:04d}",
            candidate_type=CandidateType.SINGLE_PULSE,
            dm=20.0 + i,
            snr_or_sigma=12.0 - i,
            time_sec=5.0 + i,
            rank=i + 1,
        )
        for i in range(5)
    ]


# -- summary_builder -----------------------------------------------------------


def test_summary_basic_metadata_and_no_pulsar_assumption(tmp_path: Path) -> None:
    root = tmp_path / "runs" / "r"
    root.mkdir(parents=True)
    (root / "manifest.json").write_text(
        '{"tool":"single_pulse_search","status":"SUCCESS","duration_s":5.0}',
        encoding="utf-8",
    )
    summary = build_summary(
        run_id=_RID,
        input_file="obs.fil",
        roots=[root],
        candidates=[],
        policy=ArtifactPolicy(),
        generated_at=datetime.now(UTC),
    )
    assert "single_pulse_search" in summary.tools_executed
    assert summary.candidate_counts.total == 0
    # never assume a source / pulsar when metadata is absent
    assert summary.observation.source_name is None


def test_summary_includes_warnings_when_no_metadata(tmp_path: Path) -> None:
    root = tmp_path / "runs" / "r"
    root.mkdir(parents=True)
    summary = build_summary(
        run_id=_RID,
        input_file=None,
        roots=[root],
        candidates=[],
        policy=ArtifactPolicy(),
        generated_at=datetime.now(UTC),
    )
    assert any("metadata" in w for w in summary.warnings)
    assert summary.status == "partial"


def test_summary_ghostscript_warning_is_non_blocking(tmp_path: Path) -> None:
    root = tmp_path / "runs" / "r"
    root.mkdir(parents=True)
    (root / "obs.inf").write_text(
        " Data file name without suffix          =  obs\n"
        " Telescope used                         =  Effelsberg\n"
        " Width of each time series bin (sec)    =  0.001\n"
        " Number of bins in the time series      =  10\n",
        encoding="utf-8",
    )
    summary = build_summary(
        run_id=_RID,
        input_file="obs.fil",
        roots=[root],
        candidates=[],
        policy=ArtifactPolicy(),
        generated_at=datetime.now(UTC),
        warnings=[
            "Ghostscript not found; .ps/.eps plots were not converted to PNG. Install Ghostscript to include PostScript diagnostics."
        ],
    )
    assert summary.warning_count == 1
    assert summary.status == "success"


# -- visual_builder ------------------------------------------------------------


def test_collect_visuals_publishes_png_and_thumbnail(tmp_path: Path) -> None:
    art_root = tmp_path / "runs" / "r" / "artifacts"
    art_root.mkdir(parents=True)
    Image.new("RGB", (24, 24), "white").save(art_root / "plot.png")
    am = ArtifactManager(tmp_path / "outputs", _RID)
    am.create_run()
    visuals, thumbs = collect_visuals([art_root.parent], am, make_thumbnails=True)
    assert len(visuals) == 1
    assert len(thumbs) == 1
    assert (am.run_dir / "visuals" / "plot.png").is_file()
    assert (am.run_dir / "thumbnails" / "plot.png").is_file()


def test_collect_visuals_postscript_graceful(tmp_path: Path) -> None:
    art_root = tmp_path / "runs" / "r" / "artifacts"
    art_root.mkdir(parents=True)
    (art_root / "plot.ps").write_text("%!PS-Adobe-3.0\nshowpage\n", encoding="utf-8")
    am = ArtifactManager(tmp_path / "outputs", _RID)
    am.create_run()
    # Never raises whether or not Ghostscript is installed.
    visuals, _ = collect_visuals([art_root.parent], am, make_thumbnails=False)
    if find_ghostscript() is None:
        assert any("Ghostscript" in w for w in am.warnings)
    # .ps itself is never published to the public tree
    assert not (am.run_dir / "visuals" / "plot.ps").exists()


# -- waterfall_builder ---------------------------------------------------------


def _fake_waterfall_factory(tmp_path: Path, seen: list[str]):
    def _fake(*, input_file, start_s, duration_s, dm, cmap, candidate_id):  # noqa: ANN001
        seen.append(cmap)
        out = tmp_path / f"{candidate_id}_wf.png"
        Image.new("RGB", (12, 12), "black").save(out)
        return out

    return _fake


def _one_failure_then_success_factory(tmp_path: Path):
    calls: list[str] = []

    def _fake(*, input_file, start_s, duration_s, dm, cmap, candidate_id):  # noqa: ANN001
        _ = (input_file, start_s, duration_s, dm, cmap, duration_s)
        calls.append(candidate_id)
        if candidate_id == "sp-0000":
            raise RuntimeError("waterfaller backend failed (run_id=RID): boom")
        out = tmp_path / f"{candidate_id}_wf.png"
        Image.new("RGB", (12, 12), "black").save(out)
        return out

    return _fake, calls


def _retryable_failure_factory(tmp_path: Path):
    calls: list[float] = []

    def _fake(*, input_file, start_s, duration_s, dm, cmap, candidate_id):  # noqa: ANN001
        _ = (input_file, start_s, dm, cmap, candidate_id)
        calls.append(duration_s)
        if len(calls) == 1:
            raise RuntimeError(
                "waterfaller backend failed (run_id=RID): TypeError: "
                "slice indices must be integers or None or have an __index__ method"
            )
        out = tmp_path / "retry_wf.png"
        Image.new("RGB", (12, 12), "black").save(out)
        return out

    return _fake, calls


def test_waterfall_png_only_default_cmap(tmp_path: Path) -> None:
    am = ArtifactManager(tmp_path / "outputs", _RID)
    am.create_run()
    seen: list[str] = []
    generate_waterfalls(
        _candidates(),
        am,
        policy=ArtifactPolicy(),
        options=ReportOptions(),
        waterfall_fn=_fake_waterfall_factory(tmp_path, seen),
        input_file="obs.fil",
        selection="top_n",
        top_n=3,
        export_png=True,
        export_pdf=False,
    )
    assert seen and all(c == "inferno" for c in seen)  # default colormap
    pngs = list((am.run_dir / "waterfalls").glob("*.png"))
    pdfs = list((am.run_dir / "waterfalls").glob("*.pdf"))
    assert len(pngs) == 3
    assert len(pdfs) == 0


def test_waterfall_pdf_only_when_requested(tmp_path: Path) -> None:
    am = ArtifactManager(tmp_path / "outputs", _RID)
    am.create_run()
    generate_waterfalls(
        _candidates(),
        am,
        policy=ArtifactPolicy(),
        options=ReportOptions(),
        waterfall_fn=_fake_waterfall_factory(tmp_path, []),
        input_file="obs.fil",
        selection="top_n",
        top_n=2,
        export_png=True,
        export_pdf=True,
    )
    assert len(list((am.run_dir / "waterfalls").glob("*.pdf"))) == 2


def test_waterfall_respects_max_cap(tmp_path: Path) -> None:
    am = ArtifactManager(tmp_path / "outputs", _RID)
    am.create_run()
    generate_waterfalls(
        _candidates(),
        am,
        policy=ArtifactPolicy(max_candidates_for_waterfalls=2),
        options=ReportOptions(),
        waterfall_fn=_fake_waterfall_factory(tmp_path, []),
        input_file="obs.fil",
        selection="all",
        export_png=True,
    )
    assert len(list((am.run_dir / "waterfalls").glob("*.png"))) == 2
    assert any("max_candidates_for_waterfalls" in w for w in am.warnings)


def test_waterfall_continues_after_backend_failure(tmp_path: Path) -> None:
    wf, calls = _one_failure_then_success_factory(tmp_path)
    am = ArtifactManager(tmp_path / "outputs", _RID)
    am.create_run()
    generate_waterfalls(
        _candidates(),
        am,
        policy=ArtifactPolicy(),
        options=ReportOptions(),
        waterfall_fn=wf,
        input_file="obs.fil",
        selection="all",
        export_png=True,
    )
    assert any("waterfaller backend failed" in w for w in am.warnings)
    assert not any("skipped after prior backend failure" in w for w in am.warnings)
    assert len(calls) == 5
    assert len(list((am.run_dir / "waterfalls").glob("*.png"))) == 4


def test_waterfall_retries_retryable_backend_failure(tmp_path: Path) -> None:
    wf, calls = _retryable_failure_factory(tmp_path)
    am = ArtifactManager(tmp_path / "outputs", _RID)
    am.create_run()
    generate_waterfalls(
        _candidates()[:1],
        am,
        policy=ArtifactPolicy(),
        options=ReportOptions(waterfall_window_sec=1.0),
        waterfall_fn=wf,
        input_file="obs.fil",
        selection="all",
        export_png=True,
    )
    assert len(calls) >= 2
    assert calls[1] < calls[0]
    assert any("retry succeeded with shorter window" in w for w in am.warnings)
    assert len(list((am.run_dir / "waterfalls").glob("*.png"))) == 1


# -- html_report_builder -------------------------------------------------------


def test_build_html_offline_with_tables(tmp_path: Path) -> None:
    am = ArtifactManager(tmp_path / "outputs", _RID)
    am.create_run()
    cands = _candidates()
    summary = build_summary(
        run_id=_RID,
        input_file="obs.fil",
        roots=[tmp_path],
        candidates=cands,
        policy=ArtifactPolicy(),
        generated_at=datetime.now(UTC),
    )
    manifest = ReportManifest(
        run_id=_RID,
        created_at=datetime.now(UTC),
        artifact_policy=ArtifactPolicy(),
        candidates_csv="candidates.csv",
    )
    html = build_html(
        summary=summary,
        candidates=cands,
        am=am,
        options=ReportOptions(),
        manifest=manifest,
    )
    assert "<!DOCTYPE html>" in html
    # offline: no external CDN references
    assert "http://" not in html
    assert "https://" not in html
    # candidate table + csv link + sortable JS
    assert "candidates.csv" in html
    assert "sp-0001" in html
    assert "sortTable" in html
