"""Unit tests for the observability layer (redaction / logging / run tracking)."""

from __future__ import annotations

import json
from logging.handlers import RotatingFileHandler
from pathlib import Path

from presto_mcp.observability.event_types import EventType
from presto_mcp.observability.logging_config import LoggingSettings, load_logging_settings
from presto_mcp.observability.redaction import redact_value, summarize_stream
from presto_mcp.observability.run_tracker import RunTracker
from presto_mcp.observability.schemas import PrestoCommandRecord, ToolCallRecord
from presto_mcp.observability.structured_logger import StructuredLogger
from presto_mcp.observability.tool_logging import ToolCallContext
from presto_mcp.path_security import is_run_id

_SRV = "20260101T000000Z-SRV234"
_RUN = "20260101T000000Z-RUN234"


# -- redaction -----------------------------------------------------------------


def test_redaction_hides_secrets_keeps_science() -> None:
    redacted = redact_value(
        {
            "api_key": "sk-supersecretvalue1234567890",
            "token": "abcdef",
            "dm": 57.0,
            "period": 0.0015,
            "snr": 9.2,
        }
    )
    assert redacted["api_key"] == "***REDACTED***"
    assert redacted["token"] == "***REDACTED***"
    # scientific parameters must never be redacted
    assert redacted["dm"] == 57.0
    assert redacted["period"] == 0.0015
    assert redacted["snr"] == 9.2


def test_redaction_summarizes_large_payloads() -> None:
    redacted = redact_value(list(range(500)))
    assert isinstance(redacted, list)
    assert len(redacted) <= 51  # head + overflow marker


def test_summarize_stream_clips_huge_output() -> None:
    text = "\n".join(f"line {i}" for i in range(2000))
    summary = summarize_stream(text, max_tail_lines=40)
    assert "omitted" in summary
    assert len(summary.splitlines()) < 100


# -- structured logger ---------------------------------------------------------


def test_server_session_id_and_jsonl_valid(tmp_path: Path) -> None:
    ls = LoggingSettings(log_dir=tmp_path / "logs")
    slog = StructuredLogger(ls, server_session_id=_SRV)
    assert slog.server_session_id == _SRV
    slog.log_event(EventType.SERVER_STARTUP, "server up")
    slog.log_event(EventType.TOOL_CALL_COMPLETED, "done", tool_name="presto_readfile")

    jsonl = tmp_path / "logs" / "server" / f"server-{_SRV}.jsonl"
    assert jsonl.is_file()
    lines = jsonl.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    for line in lines:  # one valid JSON object per line
        obj = json.loads(line)
        assert obj["event_type"]
        assert obj["server_session_id"] == _SRV
    assert (tmp_path / "logs" / "server" / "latest.jsonl").is_file()


def test_log_rotation_configured(tmp_path: Path) -> None:
    ls = LoggingSettings(log_dir=tmp_path / "logs", rotate_logs=True)
    slog = StructuredLogger(ls, server_session_id="20260101T000000Z-SRV235")
    assert slog._jsonl is not None
    assert any(isinstance(h, RotatingFileHandler) for h in slog._jsonl.handlers)


def test_load_logging_settings_env_overrides(tmp_path: Path) -> None:
    env = {
        "PRESTO_MCP_LOG_LEVEL": "DEBUG",
        "PRESTO_MCP_LOG_DIR": str(tmp_path / "custom"),
        "PRESTO_MCP_JSON_LOGS": "false",
    }
    ls = load_logging_settings(tmp_path, env=env)
    assert ls.level == "DEBUG"
    assert ls.log_dir == (tmp_path / "custom").resolve()
    assert ls.jsonl_enabled is False


# -- run tracker ---------------------------------------------------------------


def test_run_tracker_writes_all_files_and_status(tmp_path: Path) -> None:
    ls = LoggingSettings(log_dir=tmp_path / "logs")
    tracker = RunTracker(_RUN, ls, workflow_name="pipeline")
    tracker.workflow_started()
    tracker.record_tool_call(
        ToolCallRecord(
            tool_call_id="20260101T000001Z-TC2345",
            tool_name="presto_rfifind",
            status="completed",
            duration_ms=1840.0,
        )
    )
    tracker.record_presto_command(
        PrestoCommandRecord(
            command_id="cmd-1",
            command_name="rfifind",
            argv=["rfifind", "obs.fil"],
            return_code=0,
            status="completed",
        ),
        stdout="ok\n",
        stderr="",
    )
    tracker.workflow_completed("success")

    run_dir = tmp_path / "logs" / "runs" / _RUN
    for name in (
        "run.jsonl",
        "timeline.json",
        "tool_calls.jsonl",
        "presto_commands.jsonl",
        "status.md",
    ):
        assert (run_dir / name).is_file(), name
    # status.md is updated with the tool step
    assert "presto_rfifind" in (run_dir / "status.md").read_text(encoding="utf-8")
    # run.jsonl is valid JSON, one event per line
    for line in (run_dir / "run.jsonl").read_text(encoding="utf-8").splitlines():
        json.loads(line)


def test_run_tracker_records_failures(tmp_path: Path) -> None:
    ls = LoggingSettings(log_dir=tmp_path / "logs")
    tracker = RunTracker("20260101T000000Z-RUN235", ls)
    tracker.record_tool_call(
        ToolCallRecord(
            tool_call_id="20260101T000002Z-TC2346",
            tool_name="presto_waterfaller",
            status="failed",
            duration_ms=4210.0,
            error_type="RuntimeError",
            error_message="PSRFITS read bug",
        )
    )
    errors = tmp_path / "logs" / "runs" / "20260101T000000Z-RUN235" / "errors.jsonl"
    assert errors.is_file()
    rows = [json.loads(line) for line in errors.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["error_type"] == "RuntimeError"
    assert "PSRFITS" in rows[0]["error_message"]


# -- tool-call context ---------------------------------------------------------


def test_tool_call_id_is_generated() -> None:
    ctx = ToolCallContext("presto_readfile", workflow_run_id=None, input_summary="input_file=x")
    assert is_run_id(ctx.tool_call_id)


def test_tool_call_context_groups_into_run(tmp_path: Path) -> None:
    from presto_mcp.observability import tool_logging
    from presto_mcp.observability.run_tracker import reset_trackers

    reset_trackers()
    tool_logging.set_logging_settings(LoggingSettings(log_dir=tmp_path / "logs"))
    ctx = ToolCallContext(
        "presto_rfifind", workflow_run_id=_RUN, input_summary="time=2.0"
    )
    ctx.finish_ok(None)
    assert (tmp_path / "logs" / "runs" / _RUN / "tool_calls.jsonl").is_file()
    reset_trackers()
