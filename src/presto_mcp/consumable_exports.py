"""Copy astronomer-facing artifacts from run dirs into PRESTO_OUTPUTS_DIR."""

from __future__ import annotations

import json
import shutil
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .artifact_classification import (
    ExportClass,
    classify_artifact,
    export_class_for,
    should_skip_export,
)
from .config import Settings
from .logging_setup import phase_logger
from .models import RunStatus

log = phase_logger("export", "presto_mcp.consumable_exports")

_INDEX_NAME = "index.jsonl"
_LOCK = threading.Lock()


@dataclass(frozen=True)
class ExportedConsumable:
    """One file copied into ``outputs/<class>/``."""

    run_id: str
    tool: str
    export_class: ExportClass
    artifact: str
    src: Path
    dst: Path
    size_bytes: int
    manifest_uri: str


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _export_filename(run_id: str, tool_name: str, artifact: str) -> str:
    safe_tool = tool_name.replace("/", "_").replace("\\", "_")
    return f"{run_id}_{safe_tool}_{artifact}"


def _should_export_for_status(settings: Settings, status: RunStatus) -> bool:
    if settings.export_on_status == "ALWAYS":
        return True
    return status == RunStatus.SUCCESS


def _append_index(settings: Settings, entry: dict[str, object]) -> None:
    index_path = settings.outputs_dir / _INDEX_NAME
    line = json.dumps(entry, ensure_ascii=True, separators=(",", ":")) + "\n"
    with _LOCK:
        index_path.parent.mkdir(parents=True, exist_ok=True)
        index_path.open("a", encoding="utf-8").write(line)


def export_run_consumables(
    settings: Settings,
    *,
    run_id: str,
    tool_name: str,
    run_dir: Path,
    status: RunStatus,
    manifest_uri: str,
) -> list[ExportedConsumable]:
    """Best-effort copy of consumable artifacts; never raises."""
    if not settings.export_consumables:
        return []
    if not _should_export_for_status(settings, status):
        return []

    artifacts_dir = run_dir / "artifacts"
    if not artifacts_dir.is_dir():
        return []

    exported: list[ExportedConsumable] = []
    for src in sorted(artifacts_dir.iterdir()):
        if not src.is_file():
            continue
        name = src.name
        if should_skip_export(name):
            continue

        artifact_type = classify_artifact(name)
        export_class = export_class_for(artifact_type)
        if export_class is None or export_class not in settings.export_classes:
            continue

        try:
            size = src.stat().st_size
        except OSError as e:
            log.warning("skip export %s: cannot stat: %s", name, e)
            continue

        if size > settings.export_max_bytes:
            log.debug(
                "skip export %s: %d bytes > max %d",
                name,
                size,
                settings.export_max_bytes,
            )
            continue

        dest_dir = settings.outputs_dir / export_class
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_name = _export_filename(run_id, tool_name, name)
        dest = dest_dir / dest_name

        if dest.exists():
            log.debug("skip export %s: already at %s", name, dest)
            continue

        try:
            shutil.copy2(src, dest)
        except OSError as e:
            log.warning("export copy failed %s -> %s: %s", src, dest, e)
            continue

        record = ExportedConsumable(
            run_id=run_id,
            tool=tool_name,
            export_class=export_class,
            artifact=name,
            src=src,
            dst=dest,
            size_bytes=size,
            manifest_uri=manifest_uri,
        )
        exported.append(record)

        _append_index(
            settings,
            {
                "ts": _now_iso(),
                "run_id": run_id,
                "tool": tool_name,
                "class": export_class,
                "artifact": name,
                "src": str(src),
                "dst": str(dest),
                "size_bytes": size,
                "manifest_uri": manifest_uri,
            },
        )

    if exported:
        log.info(
            "exported %d consumable(s) for %s run_id=%s -> %s",
            len(exported),
            tool_name,
            run_id,
            settings.outputs_dir,
        )
    return exported


__all__ = ["ExportedConsumable", "export_run_consumables"]
