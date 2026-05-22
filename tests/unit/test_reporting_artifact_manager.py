"""Unit tests for the reporting ArtifactManager (extension policy + safety)."""

from __future__ import annotations

from pathlib import Path

import pytest

from presto_mcp.errors import PathSecurityError, ReportingError
from presto_mcp.reporting.artifact_manager import (
    ArtifactManager,
    is_forbidden_public,
    is_public_ext,
)
from presto_mcp.reporting.schemas import ReportArtifactKind

_RID = "20260101T000000Z-ABC234"


def _png(path: Path) -> Path:
    path.write_bytes(b"\x89PNG\r\n\x1a\n")
    return path


def test_allowed_extensions() -> None:
    for name in ("summary.json", "candidates.csv", "report.html", "report.md", "x.png", "x.pdf"):
        assert is_public_ext(name)


def test_forbidden_extensions_blocked() -> None:
    for name in ("x.dat", "x.fft", "x.inf", "x.mask", "x.pfd", "x.ps", "x.eps", "x.singlepulse"):
        assert not is_public_ext(name)
    assert is_forbidden_public("obs.singlepulse.gz")
    assert is_forbidden_public("obs.sub0001")
    assert is_forbidden_public("x.dat")
    assert not is_forbidden_public("report.html")


def test_create_run_makes_subdirs(tmp_path: Path) -> None:
    am = ArtifactManager(tmp_path / "outputs", _RID)
    am.create_run()
    for sub in ("visuals", "thumbnails", "waterfalls", "candidates", "assets"):
        assert (am.run_dir / sub).is_dir()


def test_publish_allowed(tmp_path: Path) -> None:
    am = ArtifactManager(tmp_path / "outputs", _RID)
    am.create_run()
    art = am.publish_file(
        _png(tmp_path / "s.png"), ReportArtifactKind.VISUAL_PNG, "visuals/s.png"
    )
    assert (am.run_dir / "visuals" / "s.png").is_file()
    assert art.path == "visuals/s.png"
    assert art.mime_type == "image/png"


def test_publish_forbidden_extension_rejected(tmp_path: Path) -> None:
    am = ArtifactManager(tmp_path / "outputs", _RID)
    am.create_run()
    raw = tmp_path / "x.dat"
    raw.write_bytes(b"data")
    with pytest.raises(ReportingError):
        am.publish_file(raw, ReportArtifactKind.VISUAL_PNG, "visuals/x.dat")


def test_publish_blocks_path_traversal(tmp_path: Path) -> None:
    am = ArtifactManager(tmp_path / "outputs", _RID)
    am.create_run()
    with pytest.raises(PathSecurityError):
        am.publish_file(_png(tmp_path / "s.png"), ReportArtifactKind.VISUAL_PNG, "../escape.png")


def test_publish_no_accidental_overwrite(tmp_path: Path) -> None:
    am = ArtifactManager(tmp_path / "outputs", _RID)
    am.create_run()
    src = _png(tmp_path / "s.png")
    am.publish_file(src, ReportArtifactKind.VISUAL_PNG, "visuals/s.png")
    with pytest.raises(ReportingError):
        am.publish_file(src, ReportArtifactKind.VISUAL_PNG, "visuals/s.png")


def test_write_text_allows_overwrite(tmp_path: Path) -> None:
    am = ArtifactManager(tmp_path / "outputs", _RID)
    am.create_run()
    am.write_text("summary.json", "{}", ReportArtifactKind.SUMMARY_JSON)
    am.write_text("summary.json", '{"v":1}', ReportArtifactKind.SUMMARY_JSON)
    assert (am.run_dir / "summary.json").read_text(encoding="utf-8") == '{"v":1}'


def test_publish_raw_allows_forbidden_extension(tmp_path: Path) -> None:
    am = ArtifactManager(tmp_path / "outputs", _RID)
    am.create_run()
    raw = tmp_path / "x.dat"
    raw.write_bytes(b"data")
    art = am.publish_raw(raw)
    assert (am.run_dir / "presto_raw_exports" / "x.dat").is_file()
    assert art.artifact_kind == ReportArtifactKind.RAW_EXPORT


def test_run_id_must_be_single_component(tmp_path: Path) -> None:
    with pytest.raises(PathSecurityError):
        ArtifactManager(tmp_path / "outputs", "nested/run")
