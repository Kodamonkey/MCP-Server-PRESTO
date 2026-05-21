"""Append-only audit log for MCP tool usage.

Writes newline-delimited JSON entries under ``PRESTO_LOGS_DIR`` so operators can
inspect what MCP tools were called, when, and with what outcome.
"""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from .config import Settings
from .logging_setup import phase_logger

log = phase_logger("audit", "presto_mcp.audit_log")

_LOCK = threading.Lock()
_MAX_ARG_CHARS = 1000
_SESSION_DIRNAME = "mcp_audit_sessions"
_SESSION_COUNTER = 0
_SESSION_STATE: dict[Path, tuple[str, Path]] = {}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


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


def _new_session(logs_dir: Path) -> tuple[str, Path]:
    global _SESSION_COUNTER
    _SESSION_COUNTER += 1
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    session_id = f"{stamp}-{_SESSION_COUNTER:04d}"
    path = logs_dir / _SESSION_DIRNAME / f"{session_id}.jsonl"
    return session_id, path


def initialize_audit_session(settings: Settings) -> str:
    """Start one audit session bound to the current server process."""
    settings.logs_dir.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        session_id, session_path = _new_session(settings.logs_dir)
        _SESSION_STATE[settings.logs_dir] = (session_id, session_path)
        session_path.parent.mkdir(parents=True, exist_ok=True)
        event = {
            "ts": _now_iso(),
            "tool": "__server__",
            "phase": "session_start",
            "session_id": session_id,
            "session_file": str(session_path),
            "payload": {},
        }
        line = json.dumps(event, ensure_ascii=True, separators=(",", ":")) + "\n"
        session_path.open("a", encoding="utf-8").write(line)
        log.info("session opened %s", session_id)
        return session_id


def close_audit_session(settings: Settings) -> None:
    """Close active audit session for this process."""
    settings.logs_dir.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        state = _SESSION_STATE.pop(settings.logs_dir, None)
        if state is None:
            return
        session_id, session_path = state
        event = {
            "ts": _now_iso(),
            "tool": "__server__",
            "phase": "session_stop",
            "session_id": session_id,
            "session_file": str(session_path),
            "payload": {},
        }
        line = json.dumps(event, ensure_ascii=True, separators=(",", ":")) + "\n"
        session_path.parent.mkdir(parents=True, exist_ok=True)
        session_path.open("a", encoding="utf-8").write(line)
        log.info("session closed %s", session_id)


def _resolve_session(logs_dir: Path) -> tuple[str, Path]:
    state = _SESSION_STATE.get(logs_dir)
    if state is None:
        session_id, session_path = _new_session(logs_dir)
        _SESSION_STATE[logs_dir] = (session_id, session_path)
        return session_id, session_path
    return state


def append_audit_entry(
    settings: Settings,
    *,
    tool_name: str,
    phase: str,
    payload: dict[str, Any],
) -> None:
    """Best-effort append of one audit event as JSONL."""
    settings.logs_dir.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        session_id, session_path = _resolve_session(settings.logs_dir)
        entry = {
            "ts": _now_iso(),
            "tool": tool_name,
            "phase": phase,
            "session_id": session_id,
            "session_file": str(session_path),
            "payload": _safe_jsonable(payload),
        }
        line = json.dumps(entry, ensure_ascii=True, separators=(",", ":")) + "\n"
        session_path.parent.mkdir(parents=True, exist_ok=True)
        session_path.open("a", encoding="utf-8").write(line)

