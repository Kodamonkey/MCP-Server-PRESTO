"""StructuredLogger — per-server-session human + JSONL logging with rotation.

Writes every event to:

  * ``logs/server/server-<session>.log``     — human-readable, rotating
  * ``logs/server/server-<session>.jsonl``   — one JSON object per line, rotating
  * ``logs/server/latest.log`` / ``latest.jsonl`` — mirror of the current session
  * stderr (optional console mirror)

JSONL lines are valid JSON. Sensitive values are redacted and huge payloads
summarized before they are written. An optional MCP notification hook forwards
events to the connected client when supported.
"""

from __future__ import annotations

import logging
import threading
import traceback as _tb
from collections.abc import Callable
from contextlib import suppress
from logging.handlers import RotatingFileHandler
from pathlib import Path

from ..path_security import new_run_id
from .event_types import EventType
from .logging_config import LoggingSettings
from .redaction import redact_text, redact_value
from .schemas import LogEvent

_LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


def _level_no(level: str) -> int:
    return _LEVELS.get(level.upper(), logging.INFO)


class StructuredLogger:
    """Process-wide structured logger for one server session."""

    def __init__(
        self,
        settings: LoggingSettings,
        *,
        server_session_id: str | None = None,
    ) -> None:
        self.settings = settings
        self.server_session_id = server_session_id or new_run_id()
        self._lock = threading.Lock()
        self._human: logging.Logger | None = None
        self._jsonl: logging.Logger | None = None
        self.mcp_notify: Callable[[LogEvent], None] | None = None
        if settings.enabled:
            self._setup()

    # -- setup -----------------------------------------------------------------

    def _setup(self) -> None:
        s = self.settings
        server_dir = s.log_dir / "server"
        try:
            server_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            return  # logging must never crash the server

        sid = self.server_session_id
        if s.file_enabled:
            self._human = self._make_logger(
                f"presto_mcp.obs.human.{sid}",
                [
                    server_dir / f"server-{sid}.log",
                    server_dir / "latest.log",
                ],
                console=s.console_enabled,
            )
        if s.jsonl_enabled:
            self._jsonl = self._make_logger(
                f"presto_mcp.obs.jsonl.{sid}",
                [
                    server_dir / f"server-{sid}.jsonl",
                    server_dir / "latest.jsonl",
                ],
                console=False,
            )

    def _make_logger(
        self,
        name: str,
        files: list[Path],
        *,
        console: bool,
    ) -> logging.Logger:
        logger = logging.getLogger(name)
        logger.setLevel(_level_no(self.settings.level))
        logger.propagate = False
        # Fresh handlers (avoid duplicate lines on re-init).
        for h in list(logger.handlers):
            logger.removeHandler(h)
        fmt = logging.Formatter("%(message)s")
        for i, path in enumerate(files):
            # The first file is the session file (append); 'latest.*' is
            # truncated so it always mirrors the current session.
            mode = "a" if i == 0 else "w"
            handler: logging.Handler
            if self.settings.rotate_logs:
                handler = RotatingFileHandler(
                    path,
                    maxBytes=self.settings.max_bytes,
                    backupCount=self.settings.backup_count,
                    encoding="utf-8",
                    mode=mode,
                )
            else:
                handler = logging.FileHandler(path, encoding="utf-8", mode=mode)
            handler.setFormatter(fmt)
            logger.addHandler(handler)
        if console:
            stream = logging.StreamHandler()
            stream.setFormatter(fmt)
            logger.addHandler(stream)
        return logger

    # -- emit ------------------------------------------------------------------

    def emit(self, event: LogEvent) -> None:
        """Write one already-built :class:`LogEvent` to all sinks."""
        if not self.settings.enabled:
            return
        if not event.server_session_id:
            event.server_session_id = self.server_session_id
        with self._lock:
            if self._human is not None:
                self._human.log(_level_no(event.level), event.to_human())
            if self._jsonl is not None:
                self._jsonl.info(event.to_jsonl())
        if (
            self.mcp_notify is not None
            and self.settings.mcp_client_notifications_enabled
        ):
            with suppress(Exception):  # a client hook must never break logging
                self.mcp_notify(event)

    def log_event(
        self,
        event_type: str | EventType,
        message: str,
        *,
        level: str = "INFO",
        **fields: object,
    ) -> LogEvent:
        """Build, redact and emit a :class:`LogEvent`; return it."""
        if self.settings.redact_sensitive_values:
            for key in ("input_summary", "output_summary"):
                val = fields.get(key)
                if isinstance(val, str):
                    fields[key] = redact_text(val)
            meta = fields.get("metadata")
            if isinstance(meta, dict):
                fields["metadata"] = redact_value(meta)
        event = LogEvent(
            event_type=str(event_type),
            message=message,
            level=level,
            server_session_id=self.server_session_id,
            **fields,  # type: ignore[arg-type]
        )
        self.emit(event)
        return event

    def log_exception(
        self,
        event_type: str | EventType,
        message: str,
        exc: BaseException,
        **fields: object,
    ) -> LogEvent:
        """Emit an ERROR event carrying the exception type, message + traceback."""
        tb = "".join(_tb.format_exception(type(exc), exc, exc.__traceback__))
        fields.setdefault("error_type", type(exc).__name__)
        fields.setdefault("error_message", str(exc))
        fields["traceback"] = tb
        fields.setdefault("status", "failed")
        return self.log_event(event_type, message, level="ERROR", **fields)

    # -- paths -----------------------------------------------------------------

    def server_log_paths(self) -> dict[str, str]:
        """Return the server-session log file paths (for manifests)."""
        server_dir = self.settings.log_dir / "server"
        return {
            "server_log": str(server_dir / f"server-{self.server_session_id}.log"),
            "server_jsonl": str(server_dir / f"server-{self.server_session_id}.jsonl"),
        }


# -- process-wide singleton ----------------------------------------------------

_LOGGER: StructuredLogger | None = None
_INIT_LOCK = threading.Lock()


def init_structured_logger(
    settings: LoggingSettings,
    *,
    server_session_id: str | None = None,
) -> StructuredLogger:
    """Create (or replace) the process-wide :class:`StructuredLogger`."""
    global _LOGGER
    with _INIT_LOCK:
        _LOGGER = StructuredLogger(settings, server_session_id=server_session_id)
    return _LOGGER


def get_structured_logger() -> StructuredLogger | None:
    """Return the process-wide structured logger, or ``None`` if not started."""
    return _LOGGER


def reset_structured_logger() -> None:
    """Drop the global logger (test helper)."""
    global _LOGGER
    with _INIT_LOCK:
        _LOGGER = None


__all__ = [
    "StructuredLogger",
    "get_structured_logger",
    "init_structured_logger",
    "reset_structured_logger",
]
