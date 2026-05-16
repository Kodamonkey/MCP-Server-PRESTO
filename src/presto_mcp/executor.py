"""Run orchestrator.

The executor is the only module that knows the full lifecycle of one PRESTO
invocation. Tools (`tools/*.py`) hand it a ``RunSpec``; it does paths →
container → manifest → result.

This module is async-free on purpose. Tools wrap calls in ``asyncio.to_thread``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Generic, TypeVar

from pydantic import BaseModel

from .config import Settings
from .docker_backend import BackendProtocol, build_invocation
from .errors import ManifestError, PathSecurityError
from .manifest import write_manifest
from .models import (
    BackendResult,
    ReadfileMetadata,
    RfifindSummary,
    RunManifest,
    RunStatus,
    ToolRunResult,
)
from .path_security import create_run_dir, resolve_input_path

log = logging.getLogger("presto_mcp.executor")

T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True)
class RunSpec(Generic[T]):
    """Everything the executor needs to drive one PRESTO invocation.

    ``presto_argv_builder`` is given the *resolved container input path* and
    must return the argv that follows the image name (e.g.
    ``["readfile", "/data/sample.fil"]``).

    ``parser`` consumes stdout and run-dir, returns a typed result.
    """

    tool_name: str
    input_file: str
    inputs_extra: dict[str, str]
    container_input_path: str  # logical (e.g. /data/sample.fil)
    presto_argv_builder: Callable[[str, Path], list[str]]
    parser: Callable[[str, Path], T]
    timeout_s: int
    cpus: float
    memory_mb: int


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _to_container_path(host_file: Path, host_data_dir: Path) -> str:
    """Map a host file under ``data_dir`` to its container path under ``/data``."""
    rel = host_file.resolve().relative_to(host_data_dir.resolve())
    # PRESTO containers are Linux: always forward-slash, posix-style.
    return f"/data/{rel.as_posix()}"


def _persist_logs(run_dir: Path, result: BackendResult) -> tuple[str, str]:
    stdout_path = run_dir / "stdout.log"
    stderr_path = run_dir / "stderr.log"
    stdout_path.write_text(result.stdout, encoding="utf-8", errors="replace")
    stderr_path.write_text(result.stderr, encoding="utf-8", errors="replace")
    return stdout_path.name, stderr_path.name


def _collect_artifacts(run_dir: Path) -> list[str]:
    artifacts_dir = run_dir / "artifacts"
    if not artifacts_dir.is_dir():
        return []
    return sorted(p.name for p in artifacts_dir.iterdir() if p.is_file())


def _result_uris(run_id: str, artifacts: list[str]) -> tuple[str, str, str, list[str]]:
    base = f"presto://runs/{run_id}"
    return (
        f"{base}/manifest",
        f"{base}/stdout",
        f"{base}/stderr",
        [f"{base}/artifacts/{name}" for name in artifacts],
    )


def execute(
    spec: RunSpec[T],
    settings: Settings,
    backend: BackendProtocol,
) -> ToolRunResult[T]:
    """Run one tool end-to-end. Always writes a manifest, even on failure.

    Raises ``PathSecurityError`` for bad inputs (caller's contract violation);
    container failures are returned in-band with ``status != SUCCESS``.
    """
    started_at = _now_utc()

    # 1. Resolve input path against DATA_DIR (security boundary).
    host_input = resolve_input_path(spec.input_file, settings.data_dir)
    container_input = _to_container_path(host_input, settings.data_dir)

    # 2. Allocate a run dir.
    run_id, run_dir = create_run_dir(spec.tool_name, settings.runs_dir)
    container_name = f"presto-{run_id}"

    inputs_log: dict[str, str] = {"input_file": str(host_input)}
    inputs_log.update(spec.inputs_extra)
    container_inputs: dict[str, str] = {"input_file": container_input}

    presto_argv = spec.presto_argv_builder(container_input, run_dir)

    # 3. Build invocation, run.
    invocation = build_invocation(
        image=settings.image,
        presto_argv=presto_argv,
        data_dir=settings.data_dir,
        run_dir=run_dir,
        cpus=spec.cpus,
        memory_mb=spec.memory_mb,
        container_name=container_name,
    )

    log.info("execute tool=%s run_id=%s", spec.tool_name, run_id)
    backend_result = backend.run(invocation, timeout_s=spec.timeout_s)

    # 4. Persist logs + collect artifacts.
    _persist_logs(run_dir, backend_result)
    artifacts = _collect_artifacts(run_dir)

    # 5. Parse (only on SUCCESS — otherwise we have nothing meaningful).
    parsed: T | None = None
    parse_error: str | None = None
    if backend_result.status == RunStatus.SUCCESS:
        try:
            parsed = spec.parser(backend_result.stdout, run_dir)
        except Exception as e:  # noqa: BLE001
            parse_error = f"parser failed: {type(e).__name__}: {e}"
            log.exception("parser raised for %s", spec.tool_name)

    # 6. Build manifest. Image digest is best-effort.
    finished_at = _now_utc()
    manifest = RunManifest(
        run_id=run_id,
        tool=spec.tool_name,
        status=backend_result.status if parse_error is None else RunStatus.FAILED,
        exit_code=backend_result.exit_code,
        started_at=started_at,
        finished_at=finished_at,
        duration_s=backend_result.duration_s,
        timeout_s=spec.timeout_s,
        image=settings.image,
        image_digest=_safe_digest(backend, settings.image),
        docker_argv=invocation.argv,
        presto_argv=presto_argv,
        inputs=inputs_log,
        container_inputs=container_inputs,
        cpus=spec.cpus,
        memory_mb=spec.memory_mb,
        artifacts=artifacts,
        error=(parse_error or backend_result.error),
    )

    try:
        write_manifest(run_dir, manifest)
    except ManifestError as e:
        log.exception("manifest write failed for %s", run_id)
        manifest_uri, stdout_uri, stderr_uri, artifact_uris = _result_uris(run_id, artifacts)
        return ToolRunResult[T](
            run_id=run_id,
            status=RunStatus.FAILED,
            result=None,
            manifest_uri=manifest_uri,
            stdout_uri=stdout_uri,
            stderr_uri=stderr_uri,
            artifact_uris=artifact_uris,
            error=f"manifest write failed: {e}",
        )

    manifest_uri, stdout_uri, stderr_uri, artifact_uris = _result_uris(run_id, artifacts)
    return ToolRunResult[T](
        run_id=run_id,
        status=manifest.status,
        result=parsed if manifest.status == RunStatus.SUCCESS else None,
        manifest_uri=manifest_uri,
        stdout_uri=stdout_uri,
        stderr_uri=stderr_uri,
        artifact_uris=artifact_uris,
        error=manifest.error,
    )


def _safe_digest(backend: BackendProtocol, image: str) -> str | None:
    try:
        return backend.inspect_image_digest(image)
    except Exception as e:  # noqa: BLE001
        log.warning("inspect_image_digest failed: %s", e)
        return None


# Convenience re-exports kept here so tool modules don't import models directly
__all__ = [
    "ReadfileMetadata",
    "RfifindSummary",
    "RunSpec",
    "RunStatus",
    "ToolRunResult",
    "execute",
    "PathSecurityError",
]
