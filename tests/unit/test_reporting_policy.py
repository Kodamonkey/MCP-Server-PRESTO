"""Unit tests for artifact-policy intention routing."""

from __future__ import annotations

from presto_mcp.reporting.artifact_policy import route_intention
from presto_mcp.reporting.schemas import IntentionFlags


def test_metadata_only() -> None:
    p = route_intention(IntentionFlags(wants_metadata_only=True))
    assert p.export_summary_json is True
    assert p.export_candidates_csv is False
    assert p.export_visual_png is False
    assert p.export_report_html is False


def test_candidate_search() -> None:
    p = route_intention(IntentionFlags(wants_candidates=True))
    assert p.export_summary_json is True
    assert p.export_candidates_csv is True
    assert p.export_visual_png is False


def test_visual_inspection() -> None:
    p = route_intention(IntentionFlags(wants_visuals=True))
    assert p.export_visual_png is True
    assert p.export_thumbnails is True
    assert p.export_report_html is True


def test_waterfalls() -> None:
    p = route_intention(IntentionFlags(wants_waterfalls=True))
    assert p.export_waterfall_png is True
    assert p.export_visual_png is True
    assert p.export_report_html is True


def test_waterfall_pdf() -> None:
    p = route_intention(IntentionFlags(wants_waterfall_pdf=True))
    assert p.export_waterfall_pdf is True


def test_full_report() -> None:
    p = route_intention(IntentionFlags(wants_report=True))
    assert p.export_summary_json
    assert p.export_candidates_csv
    assert p.export_visual_png
    assert p.export_thumbnails
    assert p.export_report_html
    assert p.export_report_markdown


def test_no_extra_files() -> None:
    p = route_intention(IntentionFlags(wants_no_extra_files=True))
    assert not p.export_summary_json
    assert not p.export_candidates_csv
    assert not p.export_visual_png
    assert not p.export_report_html
    assert not p.export_report_markdown


def test_original_presto_outputs() -> None:
    p = route_intention(IntentionFlags(wants_original_presto_outputs=True))
    assert p.export_original_presto_outputs is True
