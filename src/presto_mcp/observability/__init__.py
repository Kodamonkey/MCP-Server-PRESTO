"""Server-wide observability: structured logging + live run tracking.

From server startup to shutdown, every MCP request, tool call, PRESTO command,
artifact and error is recorded as a structured event:

  * ``logs/server/server-<session>.{log,jsonl}`` — per-server-session logs,
  * ``logs/runs/<run_id>/`` — per-run timeline, tool calls, PRESTO commands,
    artifacts, errors and a live human-readable ``status.md``.

Human-readable console/file logs and machine-readable JSONL run side by side;
sensitive values are redacted and huge payloads are summarized, never dumped.
"""

from __future__ import annotations
