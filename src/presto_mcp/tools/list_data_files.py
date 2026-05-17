"""Utility tool: list files under PRESTO_DATA_DIR (no PRESTO execution).

Walks the configured DATA_DIR, returns lightweight per-file summaries. Never
reads file contents. Never returns absolute paths. Symlink escapes are blocked
by ``ensure_inside_root`` on each candidate.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

from ..config import Settings, get_settings
from ..models import DataFileLikelyType, DataFileSummary, ListDataFilesResult
from ..path_security import ensure_inside_root

log = logging.getLogger("presto_mcp.tools.list_data_files")

_EXT_MAP: dict[str, DataFileLikelyType] = {
    ".fil": "filterbank",
    ".fits": "fits",
    ".fit": "fits",
    ".sf": "psrfits",
    ".psrfits": "psrfits",
    ".txt": "text",
    ".csv": "text",
}


def _classify(ext: str | None) -> DataFileLikelyType:
    if not ext:
        return "unknown"
    return _EXT_MAP.get(ext.lower(), "unknown")


def _normalize_exts(extensions: list[str] | None) -> set[str] | None:
    if extensions is None:
        return None
    out: set[str] = set()
    for raw in extensions:
        if not isinstance(raw, str) or not raw:
            continue
        e = raw.lower()
        if not e.startswith("."):
            e = "." + e
        out.add(e)
    return out or None


def run_list_data_files(
    *,
    limit: int = 100,
    extensions: list[str] | None = None,
    include_hidden: bool = False,
    settings: Settings | None = None,
) -> ListDataFilesResult:
    s = settings or get_settings()
    if limit < 1:
        limit = 1
    if limit > 10_000:
        limit = 10_000

    ext_filter = _normalize_exts(extensions)
    data_root = s.data_dir.resolve()

    if not data_root.is_dir():
        return ListDataFilesResult(
            data_dir_label="<data_dir>", count=0, files=[]
        )

    files: list[DataFileSummary] = []
    # Hard ceiling on iteration to bound work on pathological directories.
    iter_cap = max(limit * 10, 1000)
    seen = 0

    for path in data_root.rglob("*"):
        seen += 1
        if seen > iter_cap:
            break
        if len(files) >= limit:
            break

        try:
            if not path.is_file():
                continue
        except OSError:
            continue

        # Reject anything whose resolved path escapes the data root via symlink.
        try:
            ensure_inside_root(path, data_root)
        except Exception as e:  # noqa: BLE001
            log.debug("skipping path outside data_root %s: %s", path, e)
            continue

        rel = path.relative_to(data_root)
        if not include_hidden and any(part.startswith(".") for part in rel.parts):
            continue

        ext = path.suffix.lower() or None
        if ext_filter is not None and (ext is None or ext not in ext_filter):
            continue

        try:
            st = path.stat()
        except OSError:
            continue

        files.append(
            DataFileSummary(
                relative_path=rel.as_posix(),
                size_bytes=st.st_size,
                modified_at=datetime.fromtimestamp(st.st_mtime, tz=UTC),
                extension=ext,
                likely_type=_classify(ext),
            )
        )

    files.sort(key=lambda f: f.relative_path)
    return ListDataFilesResult(
        data_dir_label=_data_dir_label(data_root),
        count=len(files),
        files=files,
    )


def _data_dir_label(p: Path) -> str:
    name = p.name or "<data_dir>"
    return name


__all__ = ["run_list_data_files"]
