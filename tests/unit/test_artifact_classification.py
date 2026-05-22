from __future__ import annotations

from presto_mcp.artifact_classification import classify_artifact
from presto_mcp.models import ArtifactType


def test_classify_plots_and_rfi() -> None:
    assert classify_artifact("waterfall.png") == ArtifactType.PLOTS
    assert classify_artifact("rfi.mask") == ArtifactType.RFI


def test_classify_informative_text_and_fold() -> None:
    assert classify_artifact("candidates.csv") == ArtifactType.TIMING
    assert classify_artifact("events.groups") == ArtifactType.TIMING
    assert classify_artifact("notes.txt") == ArtifactType.TIMING
    assert classify_artifact("fold.bestprof") == ArtifactType.FOLD
    assert classify_artifact("plot.ps") == ArtifactType.PLOTS
    assert classify_artifact("candidate.cand") == ArtifactType.ACCEL_CANDIDATES


def test_classify_time_series_and_fft() -> None:
    assert classify_artifact("obs.dat") == ArtifactType.TIME_SERIES
    assert classify_artifact("obs.inf") == ArtifactType.TIME_SERIES
    assert classify_artifact("obs.fft") == ArtifactType.FFT
    assert classify_artifact("obs.singlepulse") == ArtifactType.SINGLE_PULSE
    assert classify_artifact("obs.spd") == ArtifactType.SPD
    assert classify_artifact("mystery.bin") == ArtifactType.OTHER
