"""Resource handlers backing the ``presto://runs/...`` URI scheme.

These functions are pure (filesystem only). The MCP server module wires them
into FastMCP resource templates. Each function takes the immutable
``Settings`` object so tests can build it directly.
"""

from __future__ import annotations

import json
import logging
import mimetypes
from pathlib import Path

from .config import Settings
from .errors import ManifestError, PathSecurityError
from .manifest import get_manifest
from .path_security import ensure_inside_root, is_run_id

log = logging.getLogger("presto_mcp.resources")

# Files larger than this return metadata only (size in bytes).
LARGE_ARTIFACT_BYTES = 1 * 1024 * 1024  # 1 MiB


def _run_dir(settings: Settings, run_id: str) -> Path:
    if not is_run_id(run_id):
        raise PathSecurityError(f"invalid run_id: {run_id!r}")
    run_dir = (settings.runs_dir / run_id).resolve()
    ensure_inside_root(run_dir, settings.runs_dir)
    if not run_dir.is_dir():
        raise PathSecurityError(f"run does not exist: {run_id}")
    return run_dir


def read_manifest_resource(settings: Settings, run_id: str) -> str:
    """Return the JSON text of ``runs/<id>/manifest.json``."""
    rd = _run_dir(settings, run_id)
    try:
        manifest = get_manifest(settings.runs_dir, rd.name)
    except ManifestError as e:
        raise PathSecurityError(str(e)) from e
    return manifest.model_dump_json(indent=2)


def read_log_resource(settings: Settings, run_id: str, which: str) -> str:
    if which not in {"stdout", "stderr"}:
        raise PathSecurityError(f"log stream must be 'stdout' or 'stderr', got {which!r}")
    rd = _run_dir(settings, run_id)
    log_path = rd / f"{which}.log"
    if not log_path.is_file():
        raise PathSecurityError(f"{which}.log not found for run {run_id}")
    return log_path.read_text(encoding="utf-8", errors="replace")


def read_artifact_resource(settings: Settings, run_id: str, filename: str) -> tuple[str, str]:
    """Return ``(content, mime)`` for a small artifact, or a JSON descriptor for large ones.

    Resource handlers must defend against ``..`` in the filename even though
    FastMCP usually decodes URIs for us — the URI template parser may allow
    single-level path segments through.
    """
    rd = _run_dir(settings, run_id)
    artifacts_dir = (rd / "artifacts").resolve()
    if not artifacts_dir.is_dir():
        raise PathSecurityError(f"artifacts dir missing for run {run_id}")

    # Reject anything other than a plain filename. No path components, no '..',
    # no separators of either flavor.
    if not filename or filename in {".", ".."}:
        raise PathSecurityError(f"invalid artifact name: {filename!r}")
    if "/" in filename or "\\" in filename:
        raise PathSecurityError(f"artifact name must not contain path separators: {filename!r}")

    candidate = (artifacts_dir / filename).resolve()
    ensure_inside_root(candidate, artifacts_dir)
    if not candidate.is_file():
        raise PathSecurityError(f"artifact not found: {filename}")

    size = candidate.stat().st_size
    mime, _ = mimetypes.guess_type(candidate.name)
    if size > LARGE_ARTIFACT_BYTES:
        payload = json.dumps(
            {
                "kind": "artifact-metadata",
                "name": candidate.name,
                "size_bytes": size,
                "mime": mime,
                "note": (
                    "File exceeds the in-context size limit "
                    f"({LARGE_ARTIFACT_BYTES} bytes). Open the file directly "
                    "from the host filesystem or via a downstream tool."
                ),
                "host_path": str(candidate),
            },
            indent=2,
        )
        return payload, "application/json"

    try:
        text = candidate.read_text(encoding="utf-8")
        return text, mime or "text/plain"
    except UnicodeDecodeError:
        # Binary artifact small enough to inline as a base64 blob, but FastMCP
        # text resources can't carry bytes cleanly. Return a JSON descriptor.
        payload = json.dumps(
            {
                "kind": "binary-artifact",
                "name": candidate.name,
                "size_bytes": size,
                "mime": mime or "application/octet-stream",
                "note": "Binary artifact; read via the host filesystem.",
                "host_path": str(candidate),
            },
            indent=2,
        )
        return payload, "application/json"
