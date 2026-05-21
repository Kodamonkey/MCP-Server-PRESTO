"""Tests for the presto.compile_candidate_report_pdf utility tool (no Docker)."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from presto_mcp.config import Settings
from presto_mcp.errors import PathSecurityError, PolicyViolationError
from presto_mcp.manifest import load_manifest
from presto_mcp.models import RunStatus
from presto_mcp.tools.compile_candidate_report_pdf import (
    run_compile_candidate_report_pdf,
)

RUN_A = "20260517T120000Z-AAAAAA"
RUN_B = "20260517T130000Z-BBBBBB"
RUN_EMPTY = "20260517T140000Z-EEEEEE"


def _png(path: Path, color: str) -> None:
    Image.new("RGB", (40, 30), color).save(path, "PNG")


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    data = tmp_path / "data"
    data.mkdir()
    runs = tmp_path / "runs"
    a = runs / RUN_A / "artifacts"
    a.mkdir(parents=True)
    b = runs / RUN_B / "artifacts"
    b.mkdir(parents=True)
    (runs / RUN_EMPTY / "artifacts").mkdir(parents=True)
    _png(a / "plot1.png", "red")
    _png(a / "plot2.png", "green")
    _png(b / "plot3.png", "blue")
    (a / "notes.txt").write_text("not an image", encoding="utf-8")
    return Settings(
        image="alex88ridolfi/presto5:png",
        data_dir=data.resolve(),
        runs_dir=runs.resolve(),
        outputs_dir=(tmp_path / "outputs").resolve(),
        logs_dir=(tmp_path / "logs").resolve(),
        default_cpus=2.0, default_memory_mb=1024, default_timeout_s=60,
        network="none", skip_healthcheck=True,
    )


def test_multipage_pdf(settings: Settings) -> None:
    result = run_compile_candidate_report_pdf(
        run_ids=[RUN_A, RUN_B], settings=settings,
    )
    assert result.status == RunStatus.SUCCESS
    assert result.result is not None
    assert result.result.page_count == 3
    assert len(result.result.included_artifacts) == 3
    pdf = settings.runs_dir / result.run_id / "artifacts" / result.result.pdf_file
    assert pdf.is_file() and pdf.read_bytes().startswith(b"%PDF")
    assert load_manifest(pdf.parent.parent).tool == "compile_candidate_report_pdf"


def test_title_adds_a_page(settings: Settings) -> None:
    result = run_compile_candidate_report_pdf(
        run_ids=[RUN_A], title="Candidate Review", settings=settings,
    )
    assert result.result is not None
    assert result.result.page_count == 3  # 2 images + 1 title page


def test_corrupt_image_is_skipped(settings: Settings) -> None:
    bad = settings.runs_dir / RUN_A / "artifacts" / "broken.png"
    bad.write_bytes(b"\x89PNG\r\n\x1a\nTOTALLY-NOT-A-PNG")
    result = run_compile_candidate_report_pdf(run_ids=[RUN_A], settings=settings)
    assert result.status == RunStatus.SUCCESS
    assert result.result is not None
    assert result.result.page_count == 2  # the two good PNGs
    assert any("broken.png" in s for s in result.result.skipped_artifacts)


def test_no_images_raises(settings: Settings) -> None:
    with pytest.raises(PolicyViolationError, match="no images"):
        run_compile_candidate_report_pdf(run_ids=[RUN_EMPTY], settings=settings)


def test_no_inputs_raises(settings: Settings) -> None:
    with pytest.raises(PolicyViolationError, match="run_ids"):
        run_compile_candidate_report_pdf(settings=settings)


def test_deterministic_order(settings: Settings) -> None:
    r1 = run_compile_candidate_report_pdf(run_ids=[RUN_B, RUN_A], settings=settings)
    r2 = run_compile_candidate_report_pdf(run_ids=[RUN_A, RUN_B], settings=settings)
    assert r1.result is not None and r2.result is not None
    assert r1.result.included_artifacts == r2.result.included_artifacts


def test_dedupe_identical_images(settings: Settings) -> None:
    # identical content in two runs -> collapsed to one page
    _png(settings.runs_dir / RUN_A / "artifacts" / "same.png", "purple")
    _png(settings.runs_dir / RUN_B / "artifacts" / "same.png", "purple")
    result = run_compile_candidate_report_pdf(
        run_ids=[RUN_A, RUN_B], include_patterns=["same.png"], settings=settings,
    )
    assert result.result is not None
    assert result.result.page_count == 1
    assert any("duplicate" in n for n in result.result.notes)


def test_path_traversal_blocked(settings: Settings) -> None:
    with pytest.raises(PathSecurityError):
        run_compile_candidate_report_pdf(
            artifact_paths=["/etc/passwd"], settings=settings,
        )


def test_invalid_run_id_blocked(settings: Settings) -> None:
    with pytest.raises(PathSecurityError):
        run_compile_candidate_report_pdf(
            run_ids=["not-a-valid-run-id"], settings=settings,
        )
