"""Utility tools: ``presto.summarize_run`` and ``presto.inspect_artifacts``.

Both reuse :func:`manifest.get_manifest` (which validates ``run_id``) and walk
the run's ``artifacts/`` directory. No PRESTO execution. No file contents are
read — only ``stat`` and filename heuristics.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

from ..artifact_classification import classify_artifact
from ..config import Settings, get_settings
from ..errors import ManifestError, PathSecurityError
from ..manifest import get_manifest
from ..models import (
    ArtifactSummary,
    ArtifactType,
    InspectArtifactsResult,
    RunStructuredSummary,
)
from ..path_security import ensure_inside_root, is_run_id

log = logging.getLogger("presto_mcp.tools.summarize_run")

# Largest size we consider safe to inline as text via the artifact resource.
_INLINE_TEXT_MAX_BYTES = 1 * 1024 * 1024  # 1 MiB (matches resources.LARGE_ARTIFACT_BYTES)
_INLINE_TEXT_EXTS: frozenset[str] = frozenset(
    {
        ".txt",
        ".csv",
        ".inf",
        ".bestprof",
        ".singlepulse",
        ".tim",
        ".toa",
        ".txtcand",
        ".log",
        ".json",
    }
)


def _suggest_next(types: set[ArtifactType]) -> list[str]:
    suggestions: list[str] = []
    if ArtifactType.RFI in types:
        suggestions += ["presto.prepdata", "presto.prepsubband"]
    if ArtifactType.TIME_SERIES in types:
        suggestions += ["presto.single_pulse_search", "presto.realfft"]
    if ArtifactType.FFT in types:
        suggestions += ["presto.accelsearch", "presto.zapbirds"]
    if ArtifactType.ACCEL_CANDIDATES in types:
        suggestions += ["presto.sifting", "presto.prepfold"]
    if ArtifactType.SINGLE_PULSE in types:
        suggestions += ["presto.rrattrap"]
    if ArtifactType.SPD in types:
        suggestions += ["presto.plot_spd"]
    if ArtifactType.FOLD in types:
        suggestions += ["presto.get_toas"]
    # Stable dedupe preserving first-seen order.
    seen: set[str] = set()
    out: list[str] = []
    for s in suggestions:
        if s not in seen:
            out.append(s)
            seen.add(s)
    return out


def _is_inline_readable(name: str, size_bytes: int) -> bool:
    if size_bytes > _INLINE_TEXT_MAX_BYTES:
        return False
    ext = Path(name).suffix.lower()
    return ext in _INLINE_TEXT_EXTS


def _artifact_uri(run_id: str, filename: str) -> str:
    return f"presto://runs/{run_id}/artifacts/{filename}"


def _walk_artifacts(run_dir: Path) -> list[Path]:
    artifacts_dir = (run_dir / "artifacts").resolve()
    if not artifacts_dir.is_dir():
        return []
    ensure_inside_root(artifacts_dir, run_dir.resolve())
    return sorted(p for p in artifacts_dir.iterdir() if p.is_file())


def summarize_run(
    run_id: str, *, settings: Settings | None = None
) -> RunStructuredSummary:
    s = settings or get_settings()
    if not is_run_id(run_id):
        raise PathSecurityError(f"invalid run_id: {run_id!r}")
    try:
        manifest = get_manifest(s.runs_dir, run_id)
    except ManifestError as e:
        raise PathSecurityError(str(e)) from e

    run_dir = (s.runs_dir / run_id).resolve()
    artifact_paths = _walk_artifacts(run_dir)

    counts: dict[ArtifactType, int] = {}
    by_type: dict[ArtifactType, list[str]] = {}
    for p in artifact_paths:
        t = classify_artifact(p.name)
        counts[t] = counts.get(t, 0) + 1
        by_type.setdefault(t, []).append(p.name)

    notes: list[str] = []
    on_disk = {p.name for p in artifact_paths}
    declared = set(manifest.artifacts or [])
    extra = sorted(on_disk - declared)
    missing = sorted(declared - on_disk)
    if extra:
        notes.append(
            f"{len(extra)} artifact(s) on disk not listed in manifest: "
            + ", ".join(extra[:5])
            + (" ..." if len(extra) > 5 else "")
        )
    if missing:
        notes.append(
            f"{len(missing)} manifest artifact(s) missing from disk: "
            + ", ".join(missing[:5])
            + (" ..." if len(missing) > 5 else "")
        )

    return RunStructuredSummary(
        run_id=manifest.run_id,
        tool=manifest.tool,
        status=manifest.status,
        started_at=manifest.started_at,
        duration_s=manifest.duration_s,
        exit_code=manifest.exit_code,
        error=manifest.error,
        inputs=dict(manifest.inputs),
        artifact_counts=counts,
        artifacts_by_type=by_type,
        next_suggested_tools=_suggest_next(set(counts.keys())),
        notes=notes,
    )


def inspect_artifacts(
    run_id: str, *, settings: Settings | None = None
) -> InspectArtifactsResult:
    s = settings or get_settings()
    if not is_run_id(run_id):
        raise PathSecurityError(f"invalid run_id: {run_id!r}")
    # Ensure manifest exists (consistent error surface with summarize_run).
    try:
        get_manifest(s.runs_dir, run_id)
    except ManifestError as e:
        raise PathSecurityError(str(e)) from e

    run_dir = (s.runs_dir / run_id).resolve()
    summaries: list[ArtifactSummary] = []
    for p in _walk_artifacts(run_dir):
        try:
            st = p.stat()
        except OSError:
            continue
        size = st.st_size
        summaries.append(
            ArtifactSummary(
                name=p.name,
                size_bytes=size,
                modified_at=datetime.fromtimestamp(st.st_mtime, tz=UTC),
                likely_type=classify_artifact(p.name),
                resource_uri=_artifact_uri(run_id, p.name),
                is_inline_readable=_is_inline_readable(p.name, size),
            )
        )
    return InspectArtifactsResult(run_id=run_id, artifacts=summaries)


__all__ = ["inspect_artifacts", "summarize_run"]
