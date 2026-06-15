"""RunTracker — per-run timeline, tool calls, PRESTO commands and live status.

One :class:`RunTracker` owns ``logs/runs/<run_id>/``:

  * ``run.log`` / ``run.jsonl``       — human + machine event stream
  * ``timeline.json``                 — ordered lifecycle entries
  * ``tool_calls.jsonl``              — one line per MCP tool call
  * ``presto_commands.jsonl``         — one line per PRESTO command
  * ``artifacts.jsonl``               — one line per generated artifact
  * ``errors.jsonl``                  — one line per failure
  * ``status.md``                     — live human-readable status table
  * ``commands/<id>.stdout.txt`` ...  — full captured PRESTO stdout/stderr

Every recorded event is also forwarded to the server-session
:class:`StructuredLogger` so the server log sees the whole run.
"""

from __future__ import annotations

import json
import logging
import threading
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path

from .event_types import EventType, StepStatus
from .logging_config import LoggingSettings
from .redaction import summarize_stream
from .schemas import LogEvent, PrestoCommandRecord, StatusRow, TimelineEntry, ToolCallRecord
from .status_renderer import render_status_md
from .structured_logger import StructuredLogger

log = logging.getLogger("presto_mcp.observability.run_tracker")


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


class RunTracker:
    """Track the lifecycle of one workflow run."""

    def __init__(
        self,
        run_id: str,
        settings: LoggingSettings,
        *,
        structured_logger: StructuredLogger | None = None,
        workflow_name: str | None = None,
    ) -> None:
        self.run_id = run_id
        self.settings = settings
        self.workflow_name = workflow_name or run_id
        self._slog = structured_logger
        self._lock = threading.Lock()

        self.run_dir = (settings.log_dir / "runs" / run_id).resolve()
        self.commands_dir = self.run_dir / "commands"
        self._rows: dict[str, StatusRow] = {}
        self._timeline: list[TimelineEntry] = []
        self.warning_count = 0
        self.error_count = 0
        self._ready = False
        self._init_dirs()

    def _init_dirs(self) -> None:
        try:
            self.commands_dir.mkdir(parents=True, exist_ok=True)
            self._ready = True
        except OSError as e:  # logging must never crash a workflow
            log.warning("could not create run log dir %s: %s", self.run_dir, e)

    # -- file paths ------------------------------------------------------------

    @property
    def run_log(self) -> Path:
        return self.run_dir / "run.log"

    @property
    def run_jsonl(self) -> Path:
        return self.run_dir / "run.jsonl"

    @property
    def timeline_json(self) -> Path:
        return self.run_dir / "timeline.json"

    @property
    def status_md(self) -> Path:
        return self.run_dir / "status.md"

    def log_paths(self) -> dict[str, str]:
        """Return every run-log path (relative-friendly, for manifests)."""
        return {
            "run_log": str(self.run_log),
            "run_jsonl": str(self.run_jsonl),
            "timeline_json": str(self.timeline_json),
            "tool_calls_jsonl": str(self.run_dir / "tool_calls.jsonl"),
            "presto_commands_jsonl": str(self.run_dir / "presto_commands.jsonl"),
            "artifacts_jsonl": str(self.run_dir / "artifacts.jsonl"),
            "errors_jsonl": str(self.run_dir / "errors.jsonl"),
            "status_md": str(self.status_md),
        }

    # -- low-level writers -----------------------------------------------------

    def _append_jsonl(self, name: str, payload: dict[str, object]) -> None:
        if not self._ready:
            return
        line = json.dumps(payload, ensure_ascii=True, separators=(",", ":")) + "\n"
        try:
            with (self.run_dir / name).open("a", encoding="utf-8") as fh:
                fh.write(line)
        except OSError as e:
            log.warning("run-log append failed (%s): %s", name, e)

    def _write_text(self, path: Path, text: str) -> None:
        if not self._ready:
            return
        try:
            path.write_text(text, encoding="utf-8")
        except OSError as e:
            log.warning("run-log write failed (%s): %s", path.name, e)

    def _emit(self, event: LogEvent) -> None:
        """Persist one event to run.log / run.jsonl and forward to the server log."""
        event.run_id = self.run_id
        if self._ready:
            with suppress(OSError), self.run_log.open("a", encoding="utf-8") as fh:
                fh.write(event.to_human() + "\n")
        self._append_jsonl("run.jsonl", json.loads(event.to_jsonl()))
        if self._slog is not None:
            self._slog.emit(event)

    # -- workflow lifecycle ----------------------------------------------------

    def workflow_started(self, name: str | None = None) -> None:
        if name:
            self.workflow_name = name
        self._timeline.append(
            TimelineEntry(event_type=EventType.WORKFLOW_STARTED, name=self.workflow_name)
        )
        self._emit(
            LogEvent(
                event_type=EventType.WORKFLOW_STARTED,
                message=f"workflow started: {self.workflow_name}",
                workflow_id=self.run_id,
                status=StepStatus.RUNNING,
            )
        )
        self._flush()

    def workflow_completed(self, status: str = "success") -> None:
        et = EventType.WORKFLOW_COMPLETED if status == "success" else EventType.WORKFLOW_FAILED
        self._timeline.append(
            TimelineEntry(event_type=et, name=self.workflow_name, status=status)
        )
        self._emit(
            LogEvent(
                event_type=et,
                message=f"workflow finished: {self.workflow_name} ({status})",
                workflow_id=self.run_id,
                status=status,
                level="INFO" if status == "success" else "ERROR",
            )
        )
        self._flush()

    # -- steps / tool calls ----------------------------------------------------

    def step(
        self,
        step: str,
        *,
        tool: str | None = None,
        tool_call_id: str | None = None,
        input: str | None = None,
        status: str = StepStatus.RUNNING,
        duration_s: float | None = None,
        notes: str | None = None,
    ) -> None:
        """Upsert one row of the live status table (keyed by id or step name)."""
        key = tool_call_id or step
        with self._lock:
            self._rows[key] = StatusRow(
                step=step,
                tool=tool,
                run_id=self.run_id,
                tool_call_id=tool_call_id,
                input=input,
                status=status,
                duration_s=duration_s,
                notes=notes,
            )
        self._timeline.append(
            TimelineEntry(
                event_type=_step_event(status),
                name=step,
                status=status,
                duration_ms=(duration_s * 1000.0) if duration_s is not None else None,
                detail={"tool": tool or "", "tool_call_id": tool_call_id or ""},
            )
        )
        self._flush()

    def record_tool_call(self, record: ToolCallRecord) -> None:
        """Append a tool-call record + reflect it in the status table."""
        self._append_jsonl("tool_calls.jsonl", record.model_dump())
        self.step(
            step=record.tool_name,
            tool=record.tool_name,
            tool_call_id=record.tool_call_id,
            input=record.input_summary,
            status=_tool_status(record.status),
            duration_s=(record.duration_ms / 1000.0) if record.duration_ms else None,
            notes=record.error_message or record.output_summary,
        )
        event_type = {
            "running": EventType.TOOL_CALL_STARTED,
            "completed": EventType.TOOL_CALL_COMPLETED,
            "failed": EventType.TOOL_CALL_FAILED,
        }.get(record.status, EventType.TOOL_CALL_COMPLETED)
        self._emit(
            LogEvent(
                event_type=event_type,
                message=f"tool {record.tool_name} {record.status}",
                tool_name=record.tool_name,
                tool_call_id=record.tool_call_id,
                request_id=record.request_id,
                status=record.status,
                duration_ms=record.duration_ms,
                input_summary=record.input_summary,
                output_summary=record.output_summary,
                artifact_paths=record.artifact_paths,
                error_type=record.error_type,
                error_message=record.error_message,
                level="ERROR" if record.status == "failed" else "INFO",
            )
        )
        if record.status == "failed":
            self.record_error(
                what=f"tool_call {record.tool_name}",
                error_type=record.error_type or "Error",
                error_message=record.error_message or "tool call failed",
                tool_name=record.tool_name,
                tool_call_id=record.tool_call_id,
                recovery_hint=record.recovery_hint,
            )

    # -- PRESTO commands -------------------------------------------------------

    def record_presto_command(
        self,
        record: PrestoCommandRecord,
        *,
        stdout: str | None = None,
        stderr: str | None = None,
    ) -> PrestoCommandRecord:
        """Persist a PRESTO command record + full captured stdout/stderr."""
        if self.settings.capture_stdout_stderr and self._ready:
            tail = self.settings.stdout_stderr_max_tail_lines
            if stdout is not None:
                out_path = self.commands_dir / f"{record.command_id}.stdout.txt"
                self._write_text(out_path, stdout)
                record.stdout_path = str(out_path)
                record.stdout_tail = summarize_stream(stdout, max_tail_lines=tail)
            if stderr is not None:
                err_path = self.commands_dir / f"{record.command_id}.stderr.txt"
                self._write_text(err_path, stderr)
                record.stderr_path = str(err_path)
                record.stderr_tail = summarize_stream(stderr, max_tail_lines=tail)
        self._append_jsonl("presto_commands.jsonl", record.model_dump())
        et = (
            EventType.PRESTO_COMMAND_COMPLETED
            if record.status != "running"
            else EventType.PRESTO_COMMAND_STARTED
        )
        self._emit(
            LogEvent(
                event_type=et,
                message=f"presto command {record.command_name} ({record.status})",
                tool_name=record.command_name,
                status=record.status,
                duration_ms=record.duration_ms,
                metadata={
                    "command_id": record.command_id,
                    "return_code": record.return_code,
                    "generated_files": record.generated_files,
                },
                level="ERROR" if record.return_code not in (0, None) else "INFO",
            )
        )
        return record

    # -- artifacts / warnings / errors ----------------------------------------

    def record_artifact(
        self,
        path: str,
        *,
        artifact_type: str | None = None,
        created_by_tool: str | None = None,
        candidate_id: str | None = None,
    ) -> None:
        self._append_jsonl(
            "artifacts.jsonl",
            {
                "timestamp": _now_iso(),
                "run_id": self.run_id,
                "path": path,
                "artifact_type": artifact_type,
                "created_by_tool": created_by_tool,
                "candidate_id": candidate_id,
            },
        )
        self._emit(
            LogEvent(
                event_type=EventType.ARTIFACT_GENERATED,
                message=f"artifact generated: {path}",
                tool_name=created_by_tool,
                artifact_paths=[path],
            )
        )

    def record_warning(self, message: str, **fields: object) -> None:
        self.warning_count += 1
        self._emit(
            LogEvent(
                event_type=EventType.WARNING,
                message=message,
                level="WARNING",
                **fields,  # type: ignore[arg-type]
            )
        )

    def record_error(
        self,
        *,
        what: str,
        error_type: str,
        error_message: str,
        tool_name: str | None = None,
        tool_call_id: str | None = None,
        return_code: int | None = None,
        stderr_tail: str | None = None,
        recovery_hint: str | None = None,
    ) -> None:
        self.error_count += 1
        payload = {
            "timestamp": _now_iso(),
            "run_id": self.run_id,
            "what": what,
            "error_type": error_type,
            "error_message": error_message,
            "tool_name": tool_name,
            "tool_call_id": tool_call_id,
            "return_code": return_code,
            "stderr_tail": stderr_tail,
            "recovery_hint": recovery_hint,
        }
        self._append_jsonl("errors.jsonl", payload)
        self._emit(
            LogEvent(
                event_type=EventType.ERROR,
                message=f"{what}: {error_type}: {error_message}",
                level="ERROR",
                tool_name=tool_name,
                tool_call_id=tool_call_id,
                status=StepStatus.FAILED,
                error_type=error_type,
                error_message=error_message,
                metadata={"recovery_hint": recovery_hint} if recovery_hint else {},
            )
        )

    def record_intention(self, prompt_summary: str, detail: dict[str, object]) -> None:
        """Log a routing / intention decision (no chain-of-thought)."""
        self._emit(
            LogEvent(
                event_type=EventType.INTENTION_DETECTED,
                message=f"intention detected: {prompt_summary}",
                input_summary=prompt_summary,
                metadata=detail,
            )
        )

    # -- persistence -----------------------------------------------------------

    def _flush(self) -> None:
        """Re-render ``status.md`` and ``timeline.json``."""
        if not self._ready:
            return
        with self._lock:
            rows = list(self._rows.values())
            timeline = [t.model_dump() for t in self._timeline]
        if self.settings.live_status_enabled:
            self._write_text(self.status_md, render_status_md(self.run_id, rows))
        self._write_text(
            self.timeline_json,
            json.dumps(
                {"run_id": self.run_id, "entries": timeline},
                ensure_ascii=True,
                indent=2,
            ),
        )


# -- process-wide tracker registry --------------------------------------------

_TRACKERS: dict[str, RunTracker] = {}
_TRACKER_LOCK = threading.Lock()


def get_or_create_tracker(
    run_id: str,
    settings: LoggingSettings,
    *,
    structured_logger: StructuredLogger | None = None,
    workflow_name: str | None = None,
) -> RunTracker:
    """Return the shared :class:`RunTracker` for ``run_id`` (creating it once)."""
    with _TRACKER_LOCK:
        tracker = _TRACKERS.get(run_id)
        if tracker is None:
            tracker = RunTracker(
                run_id,
                settings,
                structured_logger=structured_logger,
                workflow_name=workflow_name,
            )
            _TRACKERS[run_id] = tracker
        return tracker


def reset_trackers() -> None:
    """Drop all cached trackers (test helper)."""
    with _TRACKER_LOCK:
        _TRACKERS.clear()


def _step_event(status: str) -> str:
    if status == StepStatus.RUNNING:
        return EventType.STEP_STARTED
    if status == StepStatus.FAILED:
        return EventType.STEP_FAILED
    return EventType.STEP_COMPLETED


def _tool_status(status: str) -> str:
    return {
        "running": StepStatus.RUNNING,
        "completed": StepStatus.COMPLETED,
        "failed": StepStatus.FAILED,
        "skipped": StepStatus.SKIPPED,
        "cancelled": StepStatus.CANCELLED,
    }.get(status, StepStatus.COMPLETED)


__all__ = ["RunTracker", "get_or_create_tracker", "reset_trackers"]
