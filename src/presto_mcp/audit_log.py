"""Append-only audit log for MCP tool usage (unified session JSONL)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel

from .config import Settings
from .logging_setup import phase_logger
from .session_log import active_session, append_entry, close_session, open_session

log = phase_logger("audit", "presto_mcp.audit_log")

_MAX_ARG_CHARS = 1000


def _clip(value: str, limit: int = _MAX_ARG_CHARS) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."


def _safe_jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _safe_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_safe_jsonable(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return _clip(str(value))


def initialize_audit_session(settings: Settings) -> str:
    """Start one audit session bound to the current server process."""
    session_id, _path = open_session(settings.logs_dir)
    append_entry(
        settings.logs_dir,
        {
            "tool": "__server__",
            "phase": "session_start",
            "payload": {},
        },
    )
    log.info("session opened %s", session_id)
    return session_id


def close_audit_session(settings: Settings) -> None:
    """Close active audit session for this process."""
    state = active_session(settings.logs_dir)
    if state is None:
        return
    session_id, _path = state
    append_entry(
        settings.logs_dir,
        {
            "tool": "__server__",
            "phase": "session_stop",
            "payload": {},
        },
    )
    close_session(settings.logs_dir)
    log.info("session closed %s", session_id)


def append_audit_entry(
    settings: Settings,
    *,
    tool_name: str,
    phase: str,
    payload: dict[str, Any],
) -> None:
    """Best-effort append of one audit event as JSONL."""
    append_entry(
        settings.logs_dir,
        {
            "tool": tool_name,
            "phase": phase,
            "payload": _safe_jsonable(payload),
        },
    )
