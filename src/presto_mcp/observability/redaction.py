"""Redaction + summarization for structured logs.

Two jobs:

  * **Redact** secrets — tokens, API keys, passwords, credentials — so they
    never reach a log file.
  * **Summarize** huge payloads — big arrays, byte blobs, long PRESTO stdout —
    so logs stay readable and small.

Scientific parameters (DM, SNR, period, frequency, bandwidth, sampling time,
tool names, file basenames, artifact relative paths) are **never** redacted.
"""

from __future__ import annotations

import re

REDACTED = "***REDACTED***"

# Key names whose values must never be logged verbatim.
_SECRET_KEY_RE = re.compile(
    r"(?i)(secret|token|password|passwd|api[_-]?key|credential|"
    r"authorization|auth[_-]?token|access[_-]?key|private[_-]?key|session[_-]?key)"
)

# Heuristic for secret-looking values even under an innocuous key.
_SECRET_VALUE_RE = re.compile(r"(?i)\b(bearer\s+[a-z0-9._\-]+|sk-[a-z0-9]{16,}|ghp_[a-z0-9]{20,})")

_MAX_STR = 2000
_MAX_LIST = 50
_MAX_DEPTH = 6


def redact_value(value: object, *, _depth: int = 0) -> object:
    """Return a redacted, size-bounded copy of ``value`` safe to log."""
    if _depth > _MAX_DEPTH:
        return "<max-depth>"
    if isinstance(value, dict):
        out: dict[str, object] = {}
        for k, v in value.items():
            key = str(k)
            if _SECRET_KEY_RE.search(key):
                out[key] = REDACTED
            else:
                out[key] = redact_value(v, _depth=_depth + 1)
        return out
    if isinstance(value, (list, tuple)):
        items = list(value)
        if len(items) > _MAX_LIST:
            head = [redact_value(x, _depth=_depth + 1) for x in items[:_MAX_LIST]]
            return [*head, f"<+{len(items) - _MAX_LIST} more of {len(items)}>"]
        return [redact_value(x, _depth=_depth + 1) for x in items]
    if isinstance(value, (bytes, bytearray)):
        return f"<{len(value)} bytes>"
    if isinstance(value, str):
        return redact_text(value)
    return value


def redact_text(text: str) -> str:
    """Redact secret-looking substrings and clip very long strings."""
    cleaned = _SECRET_VALUE_RE.sub(REDACTED, text)
    if len(cleaned) > _MAX_STR:
        cleaned = f"{cleaned[:_MAX_STR]}… <clipped {len(cleaned)} chars>"
    return cleaned


def summarize_stream(text: str, *, max_tail_lines: int = 80) -> str:
    """Summarize a (possibly huge) stdout/stderr blob to head+tail lines."""
    if not text:
        return ""
    lines = text.splitlines()
    if len(lines) <= max_tail_lines:
        return redact_text(text)
    half = max(1, max_tail_lines // 2)
    head = lines[:half]
    tail = lines[-half:]
    omitted = len(lines) - len(head) - len(tail)
    joined = "\n".join([*head, f"… <{omitted} lines omitted of {len(lines)}> …", *tail])
    return redact_text(joined)


def summarize_args(args: dict[str, object]) -> str:
    """Render tool-call arguments as a short, redacted one-line summary."""
    safe = redact_value(args)
    if not isinstance(safe, dict):
        return redact_text(str(safe))
    parts: list[str] = []
    for k, v in safe.items():
        text = v if isinstance(v, str) else repr(v)
        if len(text) > 120:
            text = f"{text[:120]}…"
        parts.append(f"{k}={text}")
    line = ", ".join(parts)
    return line[:_MAX_STR]


__all__ = [
    "REDACTED",
    "redact_text",
    "redact_value",
    "summarize_args",
    "summarize_stream",
]
