"""Manifest read/write/list helpers.

A manifest is one JSON document per run at ``runs/<run_id>/manifest.json``.
Schema is :class:`presto_mcp.models.RunManifest` (schema_version=1). This module
keeps no global state; it just translates Python <-> JSON on disk.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from .errors import ManifestError
from .models import RunManifest, RunStatus, RunSummary
from .path_security import ensure_inside_root, is_run_id

log = logging.getLogger("presto_mcp.manifest")

MANIFEST_FILENAME = "manifest.json"


def manifest_path(run_dir: Path) -> Path:
    return run_dir / MANIFEST_FILENAME


def write_manifest(run_dir: Path, manifest: RunManifest) -> Path:
    """Atomically write ``manifest.json`` into ``run_dir``."""
    run_dir = run_dir.resolve()
    if not run_dir.is_dir():
        raise ManifestError(f"run_dir does not exist: {run_dir}")

    target = manifest_path(run_dir)
    tmp = target.with_suffix(".json.tmp")
    payload = manifest.model_dump_json(indent=2)
    last_err: OSError | None = None
    for attempt in range(8):
        try:
            tmp.write_text(payload, encoding="utf-8")
            # On Windows, os.replace fails if readers still hold manifest.json.
            if target.exists():
                target.unlink()
            tmp.replace(target)
            last_err = None
            break
        except OSError as e:
            last_err = e
            if attempt < 7:
                time.sleep(0.05 * (attempt + 1))
    if last_err is not None:
        raise ManifestError(f"failed to write manifest at {target}: {last_err}") from last_err

    log.debug("manifest written: %s", target)
    return target


def load_manifest(run_dir: Path) -> RunManifest:
    path = manifest_path(run_dir)
    if not path.is_file():
        raise ManifestError(f"manifest not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise ManifestError(f"failed to read/parse {path}: {e}") from e
    try:
        return RunManifest.model_validate(data)
    except Exception as e:  # pydantic ValidationError
        raise ManifestError(f"manifest {path} failed schema validation: {e}") from e


def list_run_ids(runs_root: Path) -> list[str]:
    """Return run-ids under ``runs_root`` in chronological order (newest last).

    Uses lexicographic sort, which is also chronological by construction of the
    run-id scheme. Non-conforming directory names are silently skipped.
    """
    runs_root = runs_root.resolve()
    if not runs_root.is_dir():
        return []
    ids: list[str] = []
    for child in runs_root.iterdir():
        if not child.is_dir():
            continue
        if not is_run_id(child.name):
            continue
        if not manifest_path(child).is_file():
            continue
        ids.append(child.name)
    ids.sort()
    return ids


def list_run_summaries(runs_root: Path, *, limit: int | None = None) -> list[RunSummary]:
    """Cheap, summary-only listing for ``presto.list_runs`` — newest first."""
    ids = list_run_ids(runs_root)
    ids.reverse()  # newest first
    if limit is not None:
        ids = ids[: max(0, limit)]
    summaries: list[RunSummary] = []
    for run_id in ids:
        try:
            m = load_manifest(runs_root / run_id)
        except ManifestError as e:
            log.warning("skipping unreadable manifest %s: %s", run_id, e)
            continue
        summaries.append(
            RunSummary(
                run_id=m.run_id,
                tool=m.tool,
                status=m.status,
                started_at=m.started_at,
                duration_s=m.duration_s,
                exit_code=m.exit_code,
                manifest_uri=f"presto://runs/{m.run_id}/manifest",
            )
        )
    return summaries


def get_manifest(runs_root: Path, run_id: str) -> RunManifest:
    if not is_run_id(run_id):
        raise ManifestError(f"invalid run_id: {run_id!r}")
    run_dir = (runs_root / run_id).resolve()
    ensure_inside_root(run_dir, runs_root)
    return load_manifest(run_dir)


__all__ = [
    "MANIFEST_FILENAME",
    "RunStatus",  # re-export for ergonomics
    "get_manifest",
    "list_run_ids",
    "list_run_summaries",
    "load_manifest",
    "manifest_path",
    "write_manifest",
]
