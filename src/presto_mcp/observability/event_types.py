"""Event-type and status vocabularies for the observability layer."""

from __future__ import annotations

from enum import StrEnum


class EventType(StrEnum):
    """Structured-log ``event_type`` values."""

    SERVER_STARTUP = "server_startup"
    SERVER_SHUTDOWN = "server_shutdown"

    MCP_REQUEST_RECEIVED = "mcp_request_received"
    MCP_REQUEST_ROUTED = "mcp_request_routed"
    MCP_RESPONSE_SENT = "mcp_response_sent"
    MCP_REQUEST_FAILED = "mcp_request_failed"

    TOOL_CALL_STARTED = "tool_call_started"
    TOOL_CALL_COMPLETED = "tool_call_completed"
    TOOL_CALL_FAILED = "tool_call_failed"

    PRESTO_COMMAND_STARTED = "presto_command_started"
    PRESTO_COMMAND_COMPLETED = "presto_command_completed"

    WORKFLOW_STARTED = "workflow_started"
    WORKFLOW_COMPLETED = "workflow_completed"
    WORKFLOW_FAILED = "workflow_failed"
    WORKFLOW_CANCELLED = "workflow_cancelled"

    STEP_STARTED = "step_started"
    STEP_COMPLETED = "step_completed"
    STEP_FAILED = "step_failed"

    ARTIFACT_GENERATED = "artifact_generated"
    INTENTION_DETECTED = "intention_detected"

    WARNING = "warning"
    ERROR = "error"


class StepStatus(StrEnum):
    """Lifecycle status of a workflow step / tool call."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


STATUS_SYMBOLS: dict[StepStatus, str] = {
    StepStatus.QUEUED: "⏳",      # hourglass
    StepStatus.RUNNING: "\U0001f504",  # arrows
    StepStatus.COMPLETED: "✅",   # check
    StepStatus.FAILED: "❌",      # cross
    StepStatus.SKIPPED: "⚠️",  # warning
    StepStatus.CANCELLED: "⛔",   # no entry
}


def status_symbol(status: str) -> str:
    """Return the emoji for a status value (empty string when unknown)."""
    try:
        return STATUS_SYMBOLS[StepStatus(status)]
    except ValueError:
        return ""


__all__ = ["STATUS_SYMBOLS", "EventType", "StepStatus", "status_symbol"]
