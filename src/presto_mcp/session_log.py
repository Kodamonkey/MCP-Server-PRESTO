"""Unified per-process session JSONL under ``PRESTO_LOGS_DIR/sessions/``.

Human-readable server lines (``kind=log``) and MCP tool audit events (``tool`` /
``phase`` / ``payload``) share one append-only file per server process.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

_SESSION_DIRNAME = "sessions"
_LOCK = threading.Lock()
_SESSION_COUNTER = 0
_STATE: dict[Path, tuple[str, Path]] = {}


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat()


def _write_line(path: Path, entry: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(entry, ensure_ascii=True, separators=(",", ":")) + "\n"
    path.open("a", encoding="utf-8").write(line)


def new_session_id() -> str:
    global _SESSION_COUNTER
    _SESSION_COUNTER += 1
    # Local wall-clock timestamp to match operator session time in filenames.
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    return f"{stamp}-{_SESSION_COUNTER:04d}"


def open_session(logs_dir: Path, *, session_id: str | None = None) -> tuple[str, Path]:
    """Bind one session file for this ``logs_dir`` (new id if omitted)."""
    logs_dir.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        if session_id is None:
            session_id = new_session_id()
        path = logs_dir / _SESSION_DIRNAME / f"{session_id}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        _STATE[logs_dir] = (session_id, path)
        return session_id, path


def active_session(logs_dir: Path) -> tuple[str, Path] | None:
    return _STATE.get(logs_dir)


def append_entry(logs_dir: Path, entry: dict[str, Any]) -> bool:
    """Append one JSON object to active session file.

    Fills ``ts``, ``session_id``, ``session_file``.
    Returns ``False`` when no active session exists for ``logs_dir``.
    """
    logs_dir.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        state = _STATE.get(logs_dir)
        if state is None:
            return False
        session_id, path = state
        full = {
            "ts": _now_iso(),
            "session_id": session_id,
            "session_file": str(path),
            **entry,
        }
        _write_line(path, full)
        return True


def close_session(logs_dir: Path) -> tuple[str, Path] | None:
    with _LOCK:
        return _STATE.pop(logs_dir, None)


def reset_state_for_tests() -> None:
    global _SESSION_COUNTER
    _SESSION_COUNTER = 0
    _STATE.clear()


SESSION_DIRNAME = _SESSION_DIRNAME

__all__ = [
    "SESSION_DIRNAME",
    "active_session",
    "append_entry",
    "close_session",
    "new_session_id",
    "open_session",
    "reset_state_for_tests",
]
