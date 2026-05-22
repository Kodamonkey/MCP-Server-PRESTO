"""Filename heuristics for PRESTO run artifacts."""

from __future__ import annotations

from typing import Literal

from .models import ArtifactType

ExportClass = Literal["final", "pipeline"]
OutputCategory = Literal[
    "candidatos",
    "eventos",
    "timing",
    "rfi",
    "fold",
    "visuales",
    "reportes",
    "intermedios",
]
AstronomerUtility = Literal["alta", "media", "baja"]

_SKIP_EXPORT_NAMES: frozenset[str] = frozenset(
    {
        "waterfaller_headless.py",
    }
)

_SKIP_EXPORT_SUFFIXES: frozenset[str] = frozenset(
    {
        ".py",
    }
)

_FINAL_TYPES: frozenset[ArtifactType] = frozenset(
    {
        ArtifactType.PLOTS,
        ArtifactType.TIMING,
        ArtifactType.ACCEL_CANDIDATES,
        ArtifactType.SINGLE_PULSE,
        ArtifactType.SPD,
        ArtifactType.FOLD,
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
    if "accel_" in n or n.endswith((".txtcand", ".cand")) or "bincand" in n:
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
    if n.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif", ".pdf", ".ps", ".eps")):
        return ArtifactType.PLOTS
    if n.endswith((".pfd", ".bestprof", ".prof", ".profile")):
        return ArtifactType.FOLD
    if n.endswith((".tim", ".toa")):
        return ArtifactType.TIMING
    if n.endswith((".txt", ".csv", ".groups")):
        # Informative candidate/event tables for human review.
        return ArtifactType.TIMING
    return ArtifactType.OTHER


def export_class_for(artifact_type: ArtifactType) -> ExportClass | None:
    """Map artifact type to consumable export bucket, or None to skip."""
    if artifact_type in _FINAL_TYPES:
        return "final"
    if artifact_type in _PIPELINE_TYPES or artifact_type == ArtifactType.OTHER:
        return "pipeline"
    return "pipeline"


def output_category_for(name: str, artifact_type: ArtifactType) -> OutputCategory:
    """Map one artifact into an astronomer-facing output category."""
    n = name.lower()
    if artifact_type == ArtifactType.ACCEL_CANDIDATES:
        return "candidatos"
    if artifact_type in (ArtifactType.SINGLE_PULSE, ArtifactType.SPD):
        return "eventos"
    if artifact_type == ArtifactType.TIMING:
        return "timing"
    if artifact_type == ArtifactType.RFI:
        return "rfi"
    if artifact_type == ArtifactType.FOLD:
        return "fold"
    if artifact_type == ArtifactType.PLOTS:
        return "reportes" if n.endswith(".pdf") else "visuales"
    return "intermedios"


def astronomer_utility_for(artifact_type: ArtifactType) -> AstronomerUtility:
    """Estimated scientific utility for quick triage in outputs index."""
    if artifact_type in (
        ArtifactType.ACCEL_CANDIDATES,
        ArtifactType.SINGLE_PULSE,
        ArtifactType.SPD,
        ArtifactType.TIMING,
        ArtifactType.PLOTS,
        ArtifactType.FOLD,
    ):
        return "alta"
    if artifact_type in (ArtifactType.RFI, ArtifactType.TIME_SERIES, ArtifactType.FFT):
        return "media"
    return "baja"


def should_skip_export(name: str) -> bool:
    n = name.lower()
    return name in _SKIP_EXPORT_NAMES or any(n.endswith(ext) for ext in _SKIP_EXPORT_SUFFIXES)


__all__ = [
    "AstronomerUtility",
    "ExportClass",
    "OutputCategory",
    "astronomer_utility_for",
    "classify_artifact",
    "export_class_for",
    "output_category_for",
    "should_skip_export",
]
