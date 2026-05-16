"""Reflection tools: ``presto.list_runs`` and ``presto.get_run_manifest``.

These do not run Docker. They walk ``runs/`` on the host filesystem.
"""

from __future__ import annotations

from ..config import Settings, get_settings
from ..manifest import get_manifest, list_run_summaries
from ..models import RunManifest, RunSummary


def list_runs(*, limit: int = 50, settings: Settings | None = None) -> list[RunSummary]:
    s = settings or get_settings()
    if limit < 1:
        limit = 1
    if limit > 1000:
        limit = 1000
    return list_run_summaries(s.runs_dir, limit=limit)


def get_run_manifest(run_id: str, *, settings: Settings | None = None) -> RunManifest:
    s = settings or get_settings()
    return get_manifest(s.runs_dir, run_id)
