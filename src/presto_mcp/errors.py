"""Typed exceptions surfaced as MCP error payloads.

`server.py` translates these into MCP error responses. Code outside `errors.py`
should raise the most specific subclass available and never `Exception` directly.
"""

from __future__ import annotations


class PrestoMcpError(Exception):
    """Base class for every error this server can surface."""


class PathSecurityError(PrestoMcpError):
    """A path supplied by the user/model failed the path-security checks."""


class PolicyViolationError(PrestoMcpError):
    """An input violated a numeric policy (timeout, cpus, memory, etc.)."""


class DockerInvocationError(PrestoMcpError):
    """Docker itself failed (missing binary, missing image, daemon not running).

    *Not* used for tool failures (non-zero exit from PRESTO). Those are recorded
    in the manifest with ``status=FAILED``.
    """


class ParserError(PrestoMcpError):
    """PRESTO stdout could not be parsed into the expected schema."""


class ManifestError(PrestoMcpError):
    """A manifest could not be written or loaded."""
