"""Minimal, phase-tagged logging for stderr and per-server-session files.

Console (stderr): short timestamps, ``[phase] message`` — safe for MCP stdio.
File: same lines under ``PRESTO_LOGS_DIR/server_sessions/<session_id>.log``.
"""

from __future__ import annotations

import logging
import os
import sys
from logging import LoggerAdapter
from pathlib import Path

_CONSOLE_DATEFMT = "%H:%M:%S"
_FILE_DATEFMT = "%Y-%m-%d %H:%M:%S"
_CONSOLE_FORMAT = "%(asctime)s [%(phase)s] %(message)s"
_FILE_FORMAT = "%(asctime)s [%(phase)s] %(message)s"
_SESSION_DIRNAME = "server_sessions"

_PHASE_BY_LOGGER: dict[str, str] = {
    "presto_mcp.server": "server",
    "presto_mcp.config": "startup",
    "presto_mcp.docker_runtime": "docker",
    "presto_mcp.docker_backend": "run",
    "presto_mcp.executor": "run",
    "presto_mcp.server_tools": "mcp",
    "presto_mcp.audit_log": "audit",
}

_file_handler: logging.FileHandler | None = None
_session_log_path: Path | None = None


class _PhaseFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        if not hasattr(record, "phase"):
            record.phase = _PHASE_BY_LOGGER.get(record.name, "app")
        return super().format(record)


def phase_logger(phase: str, name: str) -> LoggerAdapter:
    """Logger that always emits the given ``[phase]`` tag."""
    base = logging.getLogger(name)
    return LoggerAdapter(base, {"phase": phase})


def configure_logging(*, log_to_file: bool | None = None) -> None:
    """Configure stderr logging; file handler binds on session start."""
    level_name = os.environ.get("PRESTO_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)

    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(_PhaseFormatter(_CONSOLE_FORMAT, datefmt=_CONSOLE_DATEFMT))
    root.addHandler(console)

    for noisy in ("mcp", "httpx", "httpcore", "urllib3", "anyio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    if log_to_file is None:
        log_to_file = os.environ.get("PRESTO_LOG_TO_FILE", "true").strip().lower() not in (
            "0",
            "false",
            "no",
        )

    # File handler attaches in bind_session_log when log_to_file is true.
    root._presto_log_to_file = log_to_file  # type: ignore[attr-defined]


def bind_session_log(logs_dir: Path, session_id: str) -> Path | None:
    """Append human-readable logs for this server process to a session file."""
    global _file_handler, _session_log_path

    root = logging.getLogger()
    if getattr(root, "_presto_log_to_file", True) is False:
        return None

    unbind_session_log()
    logs_dir.mkdir(parents=True, exist_ok=True)
    path = logs_dir / _SESSION_DIRNAME / f"{session_id}.log"
    path.parent.mkdir(parents=True, exist_ok=True)

    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(_PhaseFormatter(_FILE_FORMAT, datefmt=_FILE_DATEFMT))
    logging.getLogger().addHandler(handler)

    _file_handler = handler
    _session_log_path = path
    return path


def unbind_session_log() -> None:
    """Remove the active session file handler."""
    global _file_handler, _session_log_path

    if _file_handler is not None:
        root = logging.getLogger()
        root.removeHandler(_file_handler)
        _file_handler.close()
        _file_handler = None
    _session_log_path = None


def session_log_path() -> Path | None:
    return _session_log_path


__all__ = [
    "bind_session_log",
    "configure_logging",
    "phase_logger",
    "session_log_path",
    "unbind_session_log",
]
