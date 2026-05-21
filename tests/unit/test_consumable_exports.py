from __future__ import annotations

import json
from pathlib import Path

from presto_mcp.config import Settings
from presto_mcp.consumable_exports import export_run_consumables
from presto_mcp.models import RunStatus


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        image="alex88ridolfi/presto5:png",
        data_dir=(tmp_path / "data").resolve(),
        runs_dir=(tmp_path / "runs").resolve(),
        outputs_dir=(tmp_path / "outputs").resolve(),
        logs_dir=(tmp_path / "logs").resolve(),
        default_cpus=2.0,
        default_memory_mb=1024,
        default_timeout_s=60,
        network="none",
        skip_healthcheck=True,
        export_consumables=True,
        export_classes=frozenset({"final", "pipeline"}),
        export_max_bytes=500_000_000,
        export_on_status="SUCCESS",
    )


def test_export_copies_final_and_pipeline(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    run_id = "20260101T120000Z-ABCD12"
    run_dir = settings.runs_dir / run_id / "artifacts"
    run_dir.mkdir(parents=True)
    (run_dir / "waterfall.png").write_bytes(b"\x89PNG")
    (run_dir / "rfi.mask").write_bytes(b"MASK")

    exported = export_run_consumables(
        settings,
        run_id=run_id,
        tool_name="waterfaller",
        run_dir=run_dir.parent,
        status=RunStatus.SUCCESS,
        manifest_uri=f"presto://runs/{run_id}/manifest",
    )

    assert len(exported) == 2
    assert (settings.outputs_dir / "final" / f"{run_id}_waterfaller_waterfall.png").is_file()
    assert (settings.outputs_dir / "pipeline" / f"{run_id}_waterfaller_rfi.mask").is_file()

    index_lines = (settings.outputs_dir / "index.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(index_lines) == 2
    row = json.loads(index_lines[0])
    assert row["run_id"] == run_id
    assert row["class"] in {"final", "pipeline"}


def test_export_skips_when_disabled(tmp_path: Path) -> None:
    settings = _settings(tmp_path).with_overrides(export_consumables=False)
    run_id = "20260101T120000Z-ABCD12"
    run_dir = settings.runs_dir / run_id / "artifacts"
    run_dir.mkdir(parents=True)
    (run_dir / "waterfall.png").write_bytes(b"\x89PNG")

    exported = export_run_consumables(
        settings,
        run_id=run_id,
        tool_name="waterfaller",
        run_dir=run_dir.parent,
        status=RunStatus.SUCCESS,
        manifest_uri=f"presto://runs/{run_id}/manifest",
    )
    assert exported == []
    assert not (settings.outputs_dir / "index.jsonl").exists()


def test_export_skips_failed_run_by_default(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    run_id = "20260101T120000Z-ABCD12"
    run_dir = settings.runs_dir / run_id / "artifacts"
    run_dir.mkdir(parents=True)
    (run_dir / "waterfall.png").write_bytes(b"\x89PNG")

    exported = export_run_consumables(
        settings,
        run_id=run_id,
        tool_name="waterfaller",
        run_dir=run_dir.parent,
        status=RunStatus.FAILED,
        manifest_uri=f"presto://runs/{run_id}/manifest",
    )
    assert exported == []


def test_export_skips_oversized_file(tmp_path: Path) -> None:
    settings = _settings(tmp_path).with_overrides(export_max_bytes=8)
    run_id = "20260101T120000Z-ABCD12"
    run_dir = settings.runs_dir / run_id / "artifacts"
    run_dir.mkdir(parents=True)
    (run_dir / "big.dat").write_bytes(b"\x00" * 64)

    exported = export_run_consumables(
        settings,
        run_id=run_id,
        tool_name="prepdata",
        run_dir=run_dir.parent,
        status=RunStatus.SUCCESS,
        manifest_uri=f"presto://runs/{run_id}/manifest",
    )
    assert exported == []
