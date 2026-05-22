from __future__ import annotations

from presto_mcp.artifact_classification import (
    astronomer_utility_for,
    classify_artifact,
    export_class_for,
    output_category_for,
    should_skip_export,
)
from presto_mcp.models import ArtifactType


def test_classify_plots_and_rfi() -> None:
    assert classify_artifact("waterfall.png") == ArtifactType.PLOTS
    assert classify_artifact("rfi.mask") == ArtifactType.RFI


def test_export_class_mapping() -> None:
    assert export_class_for(ArtifactType.PLOTS) == "final"
    assert export_class_for(ArtifactType.RFI) == "pipeline"
    assert export_class_for(ArtifactType.SINGLE_PULSE) == "final"
    assert export_class_for(ArtifactType.OTHER) == "pipeline"


def test_classify_informative_text_as_final_bucket() -> None:
    assert classify_artifact("candidates.csv") == ArtifactType.TIMING
    assert classify_artifact("events.groups") == ArtifactType.TIMING
    assert classify_artifact("notes.txt") == ArtifactType.TIMING
    assert classify_artifact("fold.bestprof") == ArtifactType.FOLD
    assert classify_artifact("plot.ps") == ArtifactType.PLOTS
    assert classify_artifact("candidate.cand") == ArtifactType.ACCEL_CANDIDATES


def test_skip_staged_scripts() -> None:
    assert should_skip_export("waterfaller_headless.py") is True
    assert should_skip_export("waterfall.png") is False
    assert should_skip_export("dedisp_obs.py") is True
    assert should_skip_export("candidate.ps") is False
    assert should_skip_export("fold.pfd") is False


def test_category_and_utility_mapping() -> None:
    assert output_category_for("waterfall.png", ArtifactType.PLOTS) == "visuales"
    assert output_category_for("candidate_report.pdf", ArtifactType.PLOTS) == "reportes"
    assert output_category_for("obs.singlepulse", ArtifactType.SINGLE_PULSE) == "eventos"
    assert output_category_for("obs_ACCEL_200.txtcand", ArtifactType.ACCEL_CANDIDATES) == "candidatos"
    assert output_category_for("obs.mask", ArtifactType.RFI) == "rfi"
    assert output_category_for("obs.dat", ArtifactType.TIME_SERIES) == "intermedios"
    assert astronomer_utility_for(ArtifactType.FOLD) == "alta"
    assert astronomer_utility_for(ArtifactType.RFI) == "media"
    assert astronomer_utility_for(ArtifactType.OTHER) == "baja"
