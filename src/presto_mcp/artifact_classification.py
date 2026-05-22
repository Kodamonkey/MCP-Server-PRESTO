"""Filename heuristics for PRESTO run artifacts.

Maps an artifact basename to a coarse :class:`ArtifactType`. Used by
``summarize_run`` / ``inspect_artifacts`` and by the modern reporting layer.
"""

from __future__ import annotations

from .models import ArtifactType


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


__all__ = ["classify_artifact"]
