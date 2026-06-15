"""Run orchestrator.

The executor is the only module that knows the full lifecycle of one PRESTO
invocation. Tools (`tools/*.py`) hand it a ``RunSpec``; it does paths →
container → manifest → result.

This module is async-free on purpose. Tools wrap calls in ``asyncio.to_thread``.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel

from .config import Settings
from .docker_backend import BackendProtocol, build_invocation
from .errors import ManifestError, PathSecurityError
from .manifest import write_manifest
from .models import (
    BackendResult,
    DockerInvocation,
    ReadfileMetadata,
    ResourceUsage,
    RfifindSummary,
    RunManifest,
    RunStatus,
    ToolRunResult,
)
from .path_security import (
    create_run_dir,
    is_run_artifact_path,
    resolve_input_path,
    resolve_run_artifact,
)

log = logging.getLogger("presto_mcp.executor")

T = TypeVar("T", bound=BaseModel)

InputRoot = Literal["data", "runs"]

_SEMAPHORE_LOCK = threading.Lock()
_SEMAPHORES: dict[int, threading.BoundedSemaphore] = {}


@dataclass(frozen=True)
class ExtraInput:
    """One extra input file resolved alongside the primary input."""

    path: str            # host-relative
    root: InputRoot = "data"


def extra_input_for(path: str) -> ExtraInput:
    """Build an :class:`ExtraInput` autodetecting the right root.

    Picks ``root="runs"`` when ``path`` matches ``<run_id>/artifacts/<file>``
    (e.g. an rfifind mask produced by a prior run), otherwise falls back to
    ``root="data"``. Lets pipeline tools accept either kind of mask without
    forcing callers to copy files between roots.
    """
    return ExtraInput(
        path=path,
        root="runs" if is_run_artifact_path(path) else "data",
    )


@dataclass(frozen=True)
class RunSpec(Generic[T]):
    """Everything the executor needs to drive one PRESTO invocation.

    ``presto_argv_builder`` is given ``(container_input, extra_container_paths,
    run_dir)`` and must return the argv that follows the image name (e.g.
    ``["readfile", "/data/sample.fil"]``). ``container_input`` is ``""`` when
    ``input_file is None`` (DDplan-style pure compute).

    ``parser`` consumes stdout and run-dir, returns a typed result.

    Optional fields enable richer tools:

    * ``input_root="runs"`` interprets ``input_file`` as ``<run_id>/artifacts/<file>``
      under ``runs_dir``; the executor mounts ``runs_dir`` read-only at ``/runs``.
    * ``extra_inputs`` resolves additional files (each with its own root) and
      passes their container paths to the builder as the second positional arg.
    * ``pre_invocation_hook(run_dir, host_extras)`` runs after the run dir is
      created and inputs are resolved, but before Docker is invoked. Used by
      ``sifting`` to stage many files into ``run_dir/staging/``.
    """

    tool_name: str
    input_file: str | None
    inputs_extra: dict[str, str]
    container_input_path: str  # kept for back-compat; executor fills the real one
    presto_argv_builder: Callable[[str, tuple[str, ...], Path], list[str]]
    parser: Callable[[str, Path], T]
    timeout_s: int
    cpus: float
    memory_mb: int
    input_root: InputRoot = "data"
    extra_inputs: tuple[ExtraInput, ...] = field(default_factory=tuple)
    pre_invocation_hook: Callable[[Path, tuple[Path, ...]], None] | None = None
    container_workdir: str | None = None


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _to_container_path(host_file: Path, root: Path, mount: str) -> str:
    """Map a host file under ``root`` to its container path under ``mount``."""
    rel = host_file.resolve().relative_to(root.resolve())
    return f"{mount}/{rel.as_posix()}"


def _resolve_one(path: str, root: InputRoot, settings: Settings) -> tuple[Path, str]:
    """Return (host_path, container_path) for one input."""
    if root == "data":
        host = resolve_input_path(path, settings.data_dir)
        return host, _to_container_path(host, settings.data_dir, "/data")
    if root == "runs":
        host = resolve_run_artifact(path, settings.runs_dir)
        return host, _to_container_path(host, settings.runs_dir, "/runs")
    raise PathSecurityError(f"unknown input_root: {root!r}")


def _persist_logs(run_dir: Path, result: BackendResult) -> tuple[str, str]:
    # Defensive: external sync/cleanup tools can transiently remove empty run dirs.
    # Recreate before writing logs so backend failures don't raise FileNotFoundError.
    run_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = run_dir / "stdout.log"
    stderr_path = run_dir / "stderr.log"
    stdout_path.write_text(result.stdout, encoding="utf-8", errors="replace")
    stderr_path.write_text(result.stderr, encoding="utf-8", errors="replace")
    return stdout_path.name, stderr_path.name


def _resource_usage(result: BackendResult, memory_limit_mb: int) -> ResourceUsage | None:
    """Build a :class:`ResourceUsage` from a backend result, or None if unsampled."""
    if result.resource_samples <= 0:
        return None
    return ResourceUsage(
        peak_memory_mb=result.peak_memory_mb,
        memory_limit_mb=memory_limit_mb,
        cpu_percent_peak=result.cpu_percent_peak,
        cpu_percent_avg=result.cpu_percent_avg,
        samples=result.resource_samples,
    )


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


@dataclass(frozen=True)
class _PreparedRun(Generic[T]):
    spec: RunSpec[T]
    settings: Settings
    backend: BackendProtocol
    started_at: datetime
    run_id: str
    run_dir: Path
    container_name: str
    host_input: Path | None
    container_input: str
    extra_host_paths: tuple[Path, ...]
    extra_container_paths: tuple[str, ...]
    inputs_log: dict[str, str]
    container_inputs: dict[str, str]
    presto_argv: list[str]
    invocation: DockerInvocation


def _prepare_run(
    spec: RunSpec[T],
    settings: Settings,
    backend: BackendProtocol,
) -> _PreparedRun[T]:
    """Validate paths, allocate run dir, build Docker argv. No container I/O yet."""
    host_input: Path | None = None
    container_input = ""
    if spec.input_file is not None:
        host_input, container_input = _resolve_one(spec.input_file, spec.input_root, settings)

    extra_host: list[Path] = []
    extra_container: list[str] = []
    for ex in spec.extra_inputs:
        host_e, cont_e = _resolve_one(ex.path, ex.root, settings)
        extra_host.append(host_e)
        extra_container.append(cont_e)

    run_id, run_dir = create_run_dir(spec.tool_name, settings.runs_dir)
    container_name = f"presto-{run_id}"

    inputs_log: dict[str, str] = {}
    container_inputs: dict[str, str] = {}
    if host_input is not None:
        inputs_log["input_file"] = str(host_input)
        container_inputs["input_file"] = container_input
    for i, (h, c) in enumerate(zip(extra_host, extra_container, strict=True)):
        inputs_log[f"extra_input_{i}"] = str(h)
        container_inputs[f"extra_input_{i}"] = c
    inputs_log.update(spec.inputs_extra)

    # Run any tool-specific staging hook before building argv (some hooks influence
    # what filenames the builder will reference).
    if spec.pre_invocation_hook is not None:
        spec.pre_invocation_hook(run_dir, tuple(extra_host))

    presto_argv = spec.presto_argv_builder(
        container_input, tuple(extra_container), run_dir
    )

    needs_runs_mount = spec.input_root == "runs" or any(
        ex.root == "runs" for ex in spec.extra_inputs
    )
    needs_data_mount = (
        (spec.input_file is not None and spec.input_root == "data")
        or any(ex.root == "data" for ex in spec.extra_inputs)
    )

    invocation = build_invocation(
        image=settings.image,
        presto_argv=presto_argv,
        data_dir=settings.data_dir,
        run_dir=run_dir,
        cpus=spec.cpus,
        memory_mb=spec.memory_mb,
        container_name=container_name,
        runs_dir_ro=settings.runs_dir if needs_runs_mount else None,
        workdir=spec.container_workdir,
        mount_data=needs_data_mount,
    )
    return _PreparedRun(
        spec=spec,
        settings=settings,
        backend=backend,
        started_at=_now_utc(),
        run_id=run_id,
        run_dir=run_dir,
        container_name=container_name,
        host_input=host_input,
        container_input=container_input,
        extra_host_paths=tuple(extra_host),
        extra_container_paths=tuple(extra_container),
        inputs_log=inputs_log,
        container_inputs=container_inputs,
        presto_argv=presto_argv,
        invocation=invocation,
    )


def _run_to_completion(prepared: _PreparedRun[T]) -> ToolRunResult[T]:
    """Drive Docker, parse stdout, write the final manifest."""
    spec = prepared.spec
    run_id = prepared.run_id
    run_dir = prepared.run_dir
    invocation = prepared.invocation

    log.info("start %s run_id=%s", spec.tool_name, run_id)
    try:
        backend_result = _run_backend_with_limit(prepared)
    except Exception as e:  # noqa: BLE001
        finished = _now_utc()
        backend_result = BackendResult(
            status=RunStatus.FAILED,
            exit_code=None,
            stdout="",
            stderr="",
            duration_s=(finished - prepared.started_at).total_seconds(),
            error=f"backend failed: {type(e).__name__}: {e}",
        )

    _persist_logs(run_dir, backend_result)
    artifacts = _collect_artifacts(run_dir)

    parsed: T | None = None
    parse_error: str | None = None
    if backend_result.status == RunStatus.SUCCESS:
        try:
            parsed = spec.parser(backend_result.stdout, run_dir)
        except Exception as e:  # noqa: BLE001
            parse_error = f"parser failed: {type(e).__name__}: {e}"
            log.exception("parser raised for %s", spec.tool_name)

    finished_at = _now_utc()
    manifest = RunManifest(
        run_id=run_id,
        tool=spec.tool_name,
        status=backend_result.status if parse_error is None else RunStatus.FAILED,
        exit_code=backend_result.exit_code,
        started_at=prepared.started_at,
        finished_at=finished_at,
        duration_s=backend_result.duration_s,
        timeout_s=spec.timeout_s,
        image=prepared.settings.image,
        image_digest=_safe_digest(prepared.backend, prepared.settings.image),
        docker_argv=invocation.argv,
        presto_argv=prepared.presto_argv,
        inputs=prepared.inputs_log,
        container_inputs=prepared.container_inputs,
        cpus=spec.cpus,
        memory_mb=spec.memory_mb,
        resource_usage=_resource_usage(backend_result, spec.memory_mb),
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
    _log_presto_command(manifest, backend_result)
    log.info(
        "done %s run_id=%s status=%s %.1fs",
        spec.tool_name,
        run_id,
        manifest.status,
        backend_result.duration_s,
    )
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


def _background_worker(prepared: _PreparedRun[T]) -> None:
    try:
        _run_to_completion(prepared)
    except Exception as e:  # noqa: BLE001
        log.exception("background run failed for %s", prepared.run_id)
        _write_background_failure(prepared, e)


def execute(
    spec: RunSpec[T],
    settings: Settings,
    backend: BackendProtocol,
    *,
    background: bool = False,
) -> ToolRunResult[T]:
    """Run one tool end-to-end. Always writes a manifest, even on failure.

    With ``background=True``, returns immediately with ``status=RUNNING`` after
    writing an initial manifest. The Docker invocation continues in a daemon
    thread; poll ``presto.get_run_manifest`` for the final result.

    Raises ``PathSecurityError`` for bad inputs (caller's contract violation);
    container failures are returned in-band with ``status != SUCCESS``.
    """
    prepared = _prepare_run(spec, settings, backend)

    if not background:
        return _run_to_completion(prepared)

    invocation = prepared.invocation
    running = RunManifest(
        run_id=prepared.run_id,
        tool=spec.tool_name,
        status=RunStatus.RUNNING,
        started_at=prepared.started_at,
        finished_at=None,
        duration_s=None,
        timeout_s=spec.timeout_s,
        image=settings.image,
        image_digest=None,
        docker_argv=invocation.argv,
        presto_argv=prepared.presto_argv,
        inputs=prepared.inputs_log,
        container_inputs=prepared.container_inputs,
        cpus=spec.cpus,
        memory_mb=spec.memory_mb,
        artifacts=[],
        error=None,
    )
    write_manifest(prepared.run_dir, running)

    thread = threading.Thread(
        target=_background_worker,
        args=(prepared,),
        name=f"presto-run-{prepared.run_id}",
        daemon=True,
    )
    thread.start()

    manifest_uri, stdout_uri, stderr_uri, _artifact_uris = _result_uris(prepared.run_id, [])
    return ToolRunResult[T](
        run_id=prepared.run_id,
        status=RunStatus.RUNNING,
        result=None,
        manifest_uri=manifest_uri,
        stdout_uri=stdout_uri,
        stderr_uri=stderr_uri,
        artifact_uris=[],
        error=None,
    )


def _semaphore_for(limit: int) -> threading.BoundedSemaphore:
    if limit < 1:
        limit = 1
    with _SEMAPHORE_LOCK:
        sem = _SEMAPHORES.get(limit)
        if sem is None:
            sem = threading.BoundedSemaphore(limit)
            _SEMAPHORES[limit] = sem
        return sem


def _run_backend_with_limit(prepared: _PreparedRun[T]) -> BackendResult:
    sem = _semaphore_for(prepared.settings.max_concurrent_runs)
    with sem:
        return prepared.backend.run(prepared.invocation, timeout_s=prepared.spec.timeout_s)


def _write_background_failure(prepared: _PreparedRun[T], exc: Exception) -> None:
    finished_at = _now_utc()
    duration = (finished_at - prepared.started_at).total_seconds()
    artifacts = _collect_artifacts(prepared.run_dir)
    manifest = RunManifest(
        run_id=prepared.run_id,
        tool=prepared.spec.tool_name,
        status=RunStatus.FAILED,
        exit_code=None,
        started_at=prepared.started_at,
        finished_at=finished_at,
        duration_s=duration,
        timeout_s=prepared.spec.timeout_s,
        image=prepared.settings.image,
        image_digest=None,
        docker_argv=prepared.invocation.argv,
        presto_argv=prepared.presto_argv,
        inputs=prepared.inputs_log,
        container_inputs=prepared.container_inputs,
        cpus=prepared.spec.cpus,
        memory_mb=prepared.spec.memory_mb,
        artifacts=artifacts,
        error=f"background run failed: {type(exc).__name__}: {exc}",
    )
    try:
        write_manifest(prepared.run_dir, manifest)
    except ManifestError:
        log.exception("could not write background failure manifest for %s", prepared.run_id)
        return
    _log_presto_command(manifest, None)


def _safe_digest(backend: BackendProtocol, image: str) -> str | None:
    try:
        return backend.inspect_image_digest(image)
    except Exception as e:  # noqa: BLE001
        log.warning("inspect_image_digest failed: %s", e)
        return None


def _log_presto_command(manifest: RunManifest, backend_result: BackendResult | None) -> None:
    """Emit one structured PRESTO-command event to the server-session log.

    Best-effort: observability must never break a run. No-op when the
    structured logger has not been started (e.g. under tests).
    """
    try:
        from .observability.event_types import EventType
        from .observability.redaction import summarize_stream
        from .observability.structured_logger import get_structured_logger
    except Exception:  # noqa: BLE001
        return
    slog = get_structured_logger()
    if slog is None:
        return
    try:
        meta: dict[str, object] = {
            "presto_argv": manifest.presto_argv,
            "exit_code": manifest.exit_code,
            "generated_files": manifest.artifacts,
            "stdout_path": manifest.stdout_path,
            "stderr_path": manifest.stderr_path,
        }
        if manifest.resource_usage is not None:
            meta["peak_memory_mb"] = manifest.resource_usage.peak_memory_mb
            meta["cpu_percent_avg"] = manifest.resource_usage.cpu_percent_avg
        if backend_result is not None:
            meta["stdout_tail"] = summarize_stream(backend_result.stdout, max_tail_lines=40)
            meta["stderr_tail"] = summarize_stream(backend_result.stderr, max_tail_lines=40)
        slog.log_event(
            EventType.PRESTO_COMMAND_COMPLETED,
            f"presto command {manifest.tool} finished ({manifest.status})",
            level="ERROR" if manifest.status != RunStatus.SUCCESS else "INFO",
            tool_name=manifest.tool,
            run_id=manifest.run_id,
            status=str(manifest.status),
            duration_ms=(manifest.duration_s or 0.0) * 1000.0,
            artifact_paths=manifest.artifacts,
            metadata=meta,
        )
    except Exception:  # noqa: BLE001
        log.debug("structured presto-command log failed", exc_info=True)


# Convenience re-exports kept here so tool modules don't import models directly
__all__ = [
    "ExtraInput",
    "PathSecurityError",
    "ReadfileMetadata",
    "RfifindSummary",
    "RunSpec",
    "RunStatus",
    "ToolRunResult",
    "execute",
    "extra_input_for",
]
