from __future__ import annotations

from presto_mcp.artifact_classification import (
    classify_artifact,
    export_class_for,
    should_skip_export,
)
from presto_mcp.models import ArtifactType


def test_classify_plots_and_rfi() -> None:
    assert classify_artifact("waterfall.png") == ArtifactType.PLOTS
    assert classify_artifact("rfi.mask") == ArtifactType.RFI


def test_export_class_mapping() -> None:
    assert export_class_for(ArtifactType.PLOTS) == "final"
    assert export_class_for(ArtifactType.RFI) == "pipeline"
    assert export_class_for(ArtifactType.SINGLE_PULSE) == "pipeline"


def test_skip_staged_scripts() -> None:
    assert should_skip_export("waterfaller_headless.py") is True
    assert should_skip_export("waterfall.png") is False
