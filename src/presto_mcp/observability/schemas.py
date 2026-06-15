"""Pydantic schemas for structured log events and run-tracking records."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


class LogEvent(BaseModel):
    """One structured log event — the unit written to every ``.jsonl`` log."""

    model_config = ConfigDict(extra="ignore")

    timestamp: str = Field(default_factory=_now_iso)
    level: str = "INFO"
    event_type: str
    message: str

    server_session_id: str | None = None
    run_id: str | None = None
    request_id: str | None = None
    tool_call_id: str | None = None
    workflow_id: str | None = None
    step_id: str | None = None
    tool_name: str | None = None

    status: str | None = None
    duration_ms: float | None = None

    input_summary: str | None = None
    output_summary: str | None = None
    artifact_paths: list[str] = Field(default_factory=list)

    error_type: str | None = None
    error_message: str | None = None
    traceback: str | None = None

    metadata: dict[str, object] = Field(default_factory=dict)

    def to_jsonl(self) -> str:
        """Compact single-line JSON for ``.jsonl`` logs."""
        return self.model_dump_json(exclude_none=False)

    def to_human(self) -> str:
        """Readable one-line summary for console / ``.log`` files."""
        bits = [self.timestamp, self.level, self.event_type]
        if self.tool_name:
            bits.append(f"tool={self.tool_name}")
        if self.run_id:
            bits.append(f"run={self.run_id}")
        if self.tool_call_id:
            bits.append(f"call={self.tool_call_id}")
        if self.status:
            bits.append(f"status={self.status}")
        if self.duration_ms is not None:
            bits.append(f"{self.duration_ms:.0f}ms")
        bits.append(f"- {self.message}")
        return " ".join(bits)


class ToolCallRecord(BaseModel):
    """One MCP tool-call lifecycle record (``tool_calls.jsonl``)."""

    tool_call_id: str
    tool_name: str
    request_id: str | None = None
    run_id: str | None = None
    status: str = "running"
    started_at: str = Field(default_factory=_now_iso)
    finished_at: str | None = None
    duration_ms: float | None = None
    input_summary: str | None = None
    output_summary: str | None = None
    artifact_paths: list[str] = Field(default_factory=list)
    error_type: str | None = None
    error_message: str | None = None
    recovery_hint: str | None = None


class PrestoCommandRecord(BaseModel):
    """One PRESTO command execution record (``presto_commands.jsonl``)."""

    command_id: str
    command_name: str
    argv: list[str] = Field(default_factory=list)
    cwd: str | None = None
    start_time: str = Field(default_factory=_now_iso)
    end_time: str | None = None
    duration_ms: float | None = None
    return_code: int | None = None
    stdout_path: str | None = None
    stderr_path: str | None = None
    stdout_tail: str | None = None
    stderr_tail: str | None = None
    generated_files: list[str] = Field(default_factory=list)
    expected_outputs: list[str] = Field(default_factory=list)
    missing_outputs: list[str] = Field(default_factory=list)
    status: str = "running"


class StatusRow(BaseModel):
    """One row of the live ``status.md`` table."""

    step: str
    tool: str | None = None
    run_id: str
    tool_call_id: str | None = None
    input: str | None = None
    status: str = "queued"
    duration_s: float | None = None
    notes: str | None = None


class TimelineEntry(BaseModel):
    """One entry in a run's ``timeline.json``."""

    timestamp: str = Field(default_factory=_now_iso)
    event_type: str
    name: str
    status: str | None = None
    duration_ms: float | None = None
    detail: dict[str, object] = Field(default_factory=dict)


__all__ = [
    "LogEvent",
    "PrestoCommandRecord",
    "StatusRow",
    "TimelineEntry",
    "ToolCallRecord",
]
