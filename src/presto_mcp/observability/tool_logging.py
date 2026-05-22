"""Per-tool-call structured logging used by the MCP tool decorator.

Every MCP tool call gets a ``tool_call_id`` and ``tool_call_started`` /
``tool_call_completed`` / ``tool_call_failed`` events on the server-session
log. When the client passes a valid ``workflow_run_id`` the call is also
recorded into ``logs/runs/<workflow_run_id>/`` (grouped status table).
"""

from __future__ import annotations

import logging
import time

from ..path_security import is_run_id, new_run_id
from .event_types import EventType
from .logging_config import LoggingSettings, load_logging_settings
from .run_tracker import get_or_create_tracker
from .schemas import ToolCallRecord
from .structured_logger import get_structured_logger

log = logging.getLogger("presto_mcp.observability.tool_logging")

_LOGGING_SETTINGS: LoggingSettings | None = None


def set_logging_settings(settings: LoggingSettings) -> None:
    """Install the process-wide :class:`LoggingSettings` (called at startup)."""
    global _LOGGING_SETTINGS
    _LOGGING_SETTINGS = settings


def _logging_settings() -> LoggingSettings:
    global _LOGGING_SETTINGS
    if _LOGGING_SETTINGS is None:
        from ..config import REPO_ROOT

        _LOGGING_SETTINGS = load_logging_settings(REPO_ROOT)
    return _LOGGING_SETTINGS


def _summarize_result(result: object) -> tuple[str, list[str]]:
    """Return a short ``(summary, artifact_paths)`` for a tool result."""
    if result is None:
        return "none", []
    if isinstance(result, list):
        return f"{len(result)} items", []
    status = getattr(result, "status", None)
    run_id = getattr(result, "run_id", None)
    bits: list[str] = []
    if run_id:
        bits.append(f"run_id={run_id}")
    if status is not None:
        bits.append(f"status={status}")
    artifacts: list[str] = []
    uris = getattr(result, "artifact_uris", None)
    if isinstance(uris, list):
        artifacts = [str(u) for u in uris]
    arts = getattr(result, "artifacts", None)
    if isinstance(arts, list):
        for a in arts:
            path = getattr(a, "path", None)
            if isinstance(path, str):
                artifacts.append(path)
    if not bits:
        bits.append(type(result).__name__)
    return ", ".join(bits), artifacts


def _recovery_hint(exc: BaseException) -> str | None:
    name = type(exc).__name__
    hints = {
        "PathSecurityError": "Use a path relative to DATA_DIR; no absolute paths or '..'.",
        "ReportingError": "Check run_ids/workdir exist and that the artifact extension is allowed.",
        "PolicyViolationError": "Adjust the offending numeric argument to within its allowed range.",
        "DockerInvocationError": "Verify Docker is running and the PRESTO image is present.",
    }
    return hints.get(name)


class ToolCallContext:
    """Tracks one MCP tool call from start to completion/failure."""

    def __init__(self, tool_name: str, *, workflow_run_id: str | None, input_summary: str) -> None:
        self.tool_name = tool_name
        self.tool_call_id = new_run_id()
        self._t0 = time.monotonic()
        self.slog = get_structured_logger()
        self.input_summary = input_summary
        self.workflow_run_id: str | None = None
        self.tracker = None

        if workflow_run_id and is_run_id(workflow_run_id):
            self.workflow_run_id = workflow_run_id
            try:
                self.tracker = get_or_create_tracker(
                    workflow_run_id,
                    _logging_settings(),
                    structured_logger=self.slog,
                    workflow_name=workflow_run_id,
                )
            except Exception as e:  # noqa: BLE001 - tracking must never break a call
                log.warning("could not create run tracker: %s", e)
        elif workflow_run_id:
            log.warning("ignoring malformed workflow_run_id: %r", workflow_run_id)

        if self.slog is not None:
            self.slog.log_event(
                EventType.TOOL_CALL_STARTED,
                f"tool {tool_name} started",
                tool_name=tool_name,
                tool_call_id=self.tool_call_id,
                run_id=self.workflow_run_id,
                input_summary=input_summary,
                status="running",
            )

    def _elapsed_ms(self) -> float:
        return (time.monotonic() - self._t0) * 1000.0

    def finish_ok(self, result: object) -> None:
        dur = self._elapsed_ms()
        summary, artifacts = _summarize_result(result)
        if self.slog is not None:
            self.slog.log_event(
                EventType.TOOL_CALL_COMPLETED,
                f"tool {self.tool_name} completed",
                tool_name=self.tool_name,
                tool_call_id=self.tool_call_id,
                run_id=self.workflow_run_id,
                duration_ms=dur,
                output_summary=summary,
                artifact_paths=artifacts,
                status="completed",
            )
        if self.tracker is not None:
            self.tracker.record_tool_call(
                ToolCallRecord(
                    tool_call_id=self.tool_call_id,
                    tool_name=self.tool_name,
                    run_id=self.workflow_run_id,
                    status="completed",
                    duration_ms=dur,
                    input_summary=self.input_summary,
                    output_summary=summary,
                    artifact_paths=artifacts,
                )
            )

    def finish_error(self, exc: BaseException) -> None:
        dur = self._elapsed_ms()
        if self.slog is not None:
            self.slog.log_exception(
                EventType.TOOL_CALL_FAILED,
                f"tool {self.tool_name} failed",
                exc,
                tool_name=self.tool_name,
                tool_call_id=self.tool_call_id,
                run_id=self.workflow_run_id,
                duration_ms=dur,
            )
        if self.tracker is not None:
            self.tracker.record_tool_call(
                ToolCallRecord(
                    tool_call_id=self.tool_call_id,
                    tool_name=self.tool_name,
                    run_id=self.workflow_run_id,
                    status="failed",
                    duration_ms=dur,
                    input_summary=self.input_summary,
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                    recovery_hint=_recovery_hint(exc),
                )
            )


__all__ = ["ToolCallContext", "set_logging_settings"]
