"""Logging configuration — :class:`LoggingSettings` + environment overrides.

Defaults follow the spec's ``logging:`` block. Five environment variables
override the most operationally useful knobs:

  * ``PRESTO_MCP_LOG_LEVEL``        — DEBUG / INFO / WARNING / ERROR
  * ``PRESTO_MCP_LOG_DIR``          — base directory for ``logs/``
  * ``PRESTO_MCP_JSON_LOGS``        — enable/disable JSONL logs
  * ``PRESTO_MCP_LIVE_STATUS``      — enable/disable the live ``status.md``
  * ``PRESTO_MCP_CAPTURE_STDOUT_STDERR`` — capture PRESTO stdout/stderr tails
"""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path

_VALID_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


@dataclass(frozen=True)
class LoggingSettings:
    """Immutable logging configuration for the observability layer."""

    log_dir: Path
    enabled: bool = True
    level: str = "INFO"
    console_enabled: bool = True
    jsonl_enabled: bool = True
    file_enabled: bool = True
    rotate_logs: bool = True
    max_bytes: int = 10_485_760
    backup_count: int = 10
    retention_count: int = 10
    capture_stdout_stderr: bool = True
    stdout_stderr_max_tail_lines: int = 80
    redact_sensitive_values: bool = True
    live_status_enabled: bool = True
    mcp_client_notifications_enabled: bool = True

    def with_overrides(self, **kwargs: object) -> LoggingSettings:
        return replace(self, **kwargs)  # type: ignore[arg-type]


def _env_bool(env: dict[str, str], name: str, default: bool) -> bool:
    raw = env.get(name)
    if raw is None:
        return default
    low = raw.strip().lower()
    if low in _TRUE:
        return True
    if low in _FALSE:
        return False
    return default


def _env_int(env: dict[str, str], name: str, default: int, *, minimum: int) -> int:
    raw = env.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value >= minimum else minimum


def load_logging_settings(
    repo_root: Path,
    *,
    env: dict[str, str] | None = None,
) -> LoggingSettings:
    """Build :class:`LoggingSettings` from defaults + environment overrides."""
    env = dict(os.environ if env is None else env)

    log_dir_raw = env.get("PRESTO_MCP_LOG_DIR", "").strip()
    if log_dir_raw:
        log_dir = Path(log_dir_raw)
        if not log_dir.is_absolute():
            log_dir = (repo_root / log_dir).resolve()
    else:
        log_dir = (repo_root / "logs").resolve()

    level = env.get("PRESTO_MCP_LOG_LEVEL", "INFO").strip().upper()
    if level not in _VALID_LEVELS:
        level = "INFO"

    retention = _env_int(env, "PRESTO_MCP_LOG_RETENTION", 10, minimum=1)

    return LoggingSettings(
        log_dir=log_dir,
        level=level,
        jsonl_enabled=_env_bool(env, "PRESTO_MCP_JSON_LOGS", True),
        live_status_enabled=_env_bool(env, "PRESTO_MCP_LIVE_STATUS", True),
        capture_stdout_stderr=_env_bool(env, "PRESTO_MCP_CAPTURE_STDOUT_STDERR", True),
        retention_count=retention,
    )


__all__ = ["LoggingSettings", "load_logging_settings"]
