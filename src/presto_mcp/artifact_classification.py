"""Filename heuristics for PRESTO run artifacts."""

from __future__ import annotations

from typing import Literal

from .models import ArtifactType

ExportClass = Literal["final", "pipeline"]

_SKIP_EXPORT_NAMES: frozenset[str] = frozenset(
    {
        "waterfaller_headless.py",
    }
)

_FINAL_TYPES: frozenset[ArtifactType] = frozenset(
    {
        ArtifactType.PLOTS,
        ArtifactType.FOLD,
        ArtifactType.TIMING,
    }
)

_PIPELINE_TYPES: frozenset[ArtifactType] = frozenset(
    {
        ArtifactType.RFI,
        ArtifactType.SINGLE_PULSE,
        ArtifactType.SPD,
        ArtifactType.FFT,
        ArtifactType.TIME_SERIES,
        ArtifactType.ACCEL_CANDIDATES,
    }
)


def classify_artifact(name: str) -> ArtifactType:
    """Classify an artifact filename (basename only)."""
    n = name.lower()
    if "accel_" in n or n.endswith(".txtcand"):
        return ArtifactType.ACCEL_CANDIDATES
    if n.endswith((".mask", ".rfi", ".stats", ".bytemask")):
        return ArtifactType.RFI
    if n.endswith((".dat", ".inf")):
        return ArtifactType.TIME_SERIES
    if n.endswith(".fft"):
        return ArtifactType.FFT
    if n.endswith(".singlepulse"):
        return ArtifactType.SINGLE_PULSE
    if n.endswith(".spd"):
        return ArtifactType.SPD
    if n.endswith((".png", ".ps", ".eps", ".pdf")):
        return ArtifactType.PLOTS
    if n.endswith((".pfd", ".bestprof")):
        return ArtifactType.FOLD
    if n.endswith((".tim", ".toa")):
        return ArtifactType.TIMING
    if n.endswith((".txt", ".csv", ".groups")):
        return ArtifactType.OTHER
    return ArtifactType.OTHER


def export_class_for(artifact_type: ArtifactType) -> ExportClass | None:
    """Map artifact type to consumable export bucket, or None to skip."""
    if artifact_type in _FINAL_TYPES:
        return "final"
    if artifact_type in _PIPELINE_TYPES:
        return "pipeline"
    if artifact_type == ArtifactType.OTHER:
        return "pipeline"
    return None


def should_skip_export(name: str) -> bool:
    return name in _SKIP_EXPORT_NAMES


__all__ = [
    "ExportClass",
    "classify_artifact",
    "export_class_for",
    "should_skip_export",
]
