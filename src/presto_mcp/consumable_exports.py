"""Copy astronomer-facing artifacts from run dirs into PRESTO_OUTPUTS_DIR."""

from __future__ import annotations

import json
import shutil
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .artifact_classification import (
    AstronomerUtility,
    ExportClass,
    OutputCategory,
    astronomer_utility_for,
    classify_artifact,
    export_class_for,
    output_category_for,
    should_skip_export,
)
from .config import Settings
from .logging_setup import phase_logger
from .models import RunStatus

log = phase_logger("export", "presto_mcp.consumable_exports")

_LEGACY_INDEX_NAME = "index.jsonl"
_INDEX_DIRNAME = "index"
_V2_EVENTS_NAME = "events.v2.jsonl"
_V2_CATALOG_NAME = "catalog.v2.json"
_BY_RUN_DIRNAME = "by_run"
_LOCK = threading.Lock()


@dataclass(frozen=True)
class ExportedConsumable:
    """One file copied into ``outputs/by_run/<run_id>/<category>/``."""

    run_id: str
    tool: str
    export_class: ExportClass
    category: OutputCategory
    utility: AstronomerUtility
    artifact_type: str
    artifact: str
    src: Path
    dst: Path
    size_bytes: int
    manifest_uri: str


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _safe_tool(tool_name: str) -> str:
    safe_tool = tool_name.replace("/", "_").replace("\\", "_")
    return "".join(ch if ch.isalnum() or ch in {"_", "-", "."} else "_" for ch in safe_tool)


def _resolve_dest(
    settings: Settings,
    *,
    run_id: str,
    category: OutputCategory,
    tool_name: str,
    artifact: str,
) -> Path:
    base_dir = settings.outputs_dir / _BY_RUN_DIRNAME / run_id / category
    base_dir.mkdir(parents=True, exist_ok=True)
    dest = base_dir / artifact
    if not dest.exists():
        return dest
    # Collision guard when different artifacts share basename in one run.
    return base_dir / f"{_safe_tool(tool_name)}__{artifact}"


def _should_export_for_status(settings: Settings, status: RunStatus) -> bool:
    if settings.export_on_status == "ALWAYS":
        return True
    return status == RunStatus.SUCCESS


def _append_jsonl(path: Path, entry: dict[str, object]) -> None:
    line = json.dumps(entry, ensure_ascii=True, separators=(",", ":")) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.open("a", encoding="utf-8").write(line)


def _read_manifest_input_refs(run_dir: Path) -> list[str]:
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.is_file():
        return []
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return []
    inputs = raw.get("inputs")
    if not isinstance(inputs, dict):
        return []
    refs: list[str] = []
    for v in inputs.values():
        if isinstance(v, str) and v.strip():
            refs.append(v)
    return sorted(set(refs))


def _load_catalog(path: Path) -> dict[str, object]:
    if not path.is_file():
        return {"schema_version": 2, "updated_at": _now_iso(), "runs": {}}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {"schema_version": 2, "updated_at": _now_iso(), "runs": {}}
    if not isinstance(raw, dict):
        return {"schema_version": 2, "updated_at": _now_iso(), "runs": {}}
    runs = raw.get("runs")
    if not isinstance(runs, dict):
        raw["runs"] = {}
    raw["schema_version"] = 2
    return raw


def _update_catalog(
    catalog: dict[str, object],
    *,
    run_id: str,
    tool_name: str,
    status: RunStatus,
    manifest_uri: str,
    input_refs: list[str],
    record: ExportedConsumable,
) -> None:
    runs = catalog.setdefault("runs", {})
    if not isinstance(runs, dict):
        return
    run_obj = runs.setdefault(
        run_id,
        {
            "tool": tool_name,
            "status": str(status),
            "manifest_uri": manifest_uri,
            "input_refs": input_refs,
            "categories": {},
        },
    )
    if not isinstance(run_obj, dict):
        return
    run_obj["tool"] = tool_name
    run_obj["status"] = str(status)
    run_obj["manifest_uri"] = manifest_uri
    run_obj["input_refs"] = input_refs
    categories = run_obj.setdefault("categories", {})
    if not isinstance(categories, dict):
        return
    rows = categories.setdefault(record.category, [])
    if not isinstance(rows, list):
        return
    rows.append(
        {
            "artifact": record.artifact,
            "artifact_type": record.artifact_type,
            "consumer_role": record.export_class,
            "utilidad_astronomo": record.utility,
            "dst": str(record.dst),
            "size_bytes": record.size_bytes,
        }
    )


def _append_indexes(
    settings: Settings,
    *,
    run_id: str,
    tool_name: str,
    status: RunStatus,
    manifest_uri: str,
    input_refs: list[str],
    record: ExportedConsumable,
) -> None:
    legacy_path = settings.outputs_dir / _LEGACY_INDEX_NAME
    v2_events_path = settings.outputs_dir / _INDEX_DIRNAME / _V2_EVENTS_NAME
    v2_catalog_path = settings.outputs_dir / _INDEX_DIRNAME / _V2_CATALOG_NAME
    with _LOCK:
        base = {
            "ts": _now_iso(),
            "run_id": run_id,
            "tool": tool_name,
            "status": str(status),
            "artifact": record.artifact,
            "src": str(record.src),
            "dst": str(record.dst),
            "size_bytes": record.size_bytes,
            "manifest_uri": manifest_uri,
            "input_refs": input_refs,
        }
        _append_jsonl(
            legacy_path,
            {
                **base,
                "class": record.export_class,
                "category": record.category,
                "artifact_type": record.artifact_type,
                "utilidad_astronomo": record.utility,
            },
        )
        _append_jsonl(
            v2_events_path,
            {
                "schema_version": 2,
                **base,
                "consumer_role": record.export_class,
                "categoria": record.category,
                "artifact_type": record.artifact_type,
                "utilidad_astronomo": record.utility,
            },
        )
        catalog = _load_catalog(v2_catalog_path)
        _update_catalog(
            catalog,
            run_id=run_id,
            tool_name=tool_name,
            status=status,
            manifest_uri=manifest_uri,
            input_refs=input_refs,
            record=record,
        )
        catalog["updated_at"] = _now_iso()
        v2_catalog_path.parent.mkdir(parents=True, exist_ok=True)
        v2_catalog_path.write_text(
            json.dumps(catalog, ensure_ascii=True, indent=2) + "\n",
            encoding="utf-8",
        )


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

    input_refs = _read_manifest_input_refs(run_dir)
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
        category = output_category_for(name, artifact_type)
        utility = astronomer_utility_for(artifact_type)

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

        dest = _resolve_dest(
            settings,
            run_id=run_id,
            category=category,
            tool_name=tool_name,
            artifact=name,
        )

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
            category=category,
            utility=utility,
            artifact_type=artifact_type.value,
            artifact=name,
            src=src,
            dst=dest,
            size_bytes=size,
            manifest_uri=manifest_uri,
        )
        exported.append(record)

        _append_indexes(
            settings,
            run_id=run_id,
            tool_name=tool_name,
            status=status,
            manifest_uri=manifest_uri,
            input_refs=input_refs,
            record=record,
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
