"""Path-security primitives.

Every path that originates from the model/user is funnelled through
:func:`resolve_input_path` before it reaches the executor. Outputs are written
only into run-dirs created by :func:`create_run_dir`. :func:`ensure_inside_root`
is the reusable invariant relied on by tools and resource handlers.
"""

from __future__ import annotations

import base64
import logging
import os
import re
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from .errors import PathSecurityError

log = logging.getLogger("presto_mcp.path_security")

# Single regex for run-id readability (timestamp + 6-char base32 nonce).
_RUN_ID_RE = re.compile(r"^\d{8}T\d{6}Z-[A-Z2-7]{6}$")

# Names that would create path components surprising on either OS.
_FORBIDDEN_NAMES = {"", ".", ".."}


def _is_absolute_anywhere(s: str) -> bool:
    """Reject anything that looks absolute on either Windows or POSIX."""
    if not s:
        return False
    if s.startswith(("/", "\\")):
        return True
    # Drive letters: "C:\foo" or "C:foo" or even "C:".
    if len(s) >= 2 and s[1] == ":" and s[0].isalpha():
        return True
    # UNC paths "\\server\share".
    return s.startswith("\\\\")


def _has_traversal_segment(s: str) -> bool:
    # Normalize separators for the check, but never use the normalized string elsewhere.
    parts = s.replace("\\", "/").split("/")
    return any(p in _FORBIDDEN_NAMES for p in parts) or ".." in parts


def resolve_input_path(relative_path: str, data_root: Path) -> Path:
    """Resolve a user-supplied relative path against ``data_root``.

    Rejects: empty input, absolute paths (any flavor), ``..`` segments, paths
    that resolve outside ``data_root``, and paths whose resolved on-disk name
    differs in case from the input (case-folding attack on Windows hosts).
    """
    if not isinstance(relative_path, str):
        raise PathSecurityError(f"input path must be a string, got {type(relative_path).__name__}")

    s = relative_path.strip()
    if not s:
        raise PathSecurityError("input path is empty")

    if _is_absolute_anywhere(s):
        raise PathSecurityError(f"absolute paths are not allowed: {relative_path!r}")

    if _has_traversal_segment(s):
        raise PathSecurityError(
            f"path contains forbidden segment ('..', '.', empty): {relative_path!r}"
        )

    # Build candidate under data_root using forward-slash semantics, then resolve.
    root_resolved = data_root.resolve()
    candidate = (root_resolved / PurePosixPath(s.replace("\\", "/"))).resolve(strict=False)

    if not candidate.exists():
        raise PathSecurityError(f"input file does not exist: {relative_path!r}")

    # Re-resolve strict now that we know it exists (follows symlinks).
    candidate = candidate.resolve(strict=True)

    ensure_inside_root(candidate, root_resolved)

    # Case-folding check: the on-disk name(s) must match the input case for the
    # final component(s). We compare the suffix path the user supplied against
    # the corresponding suffix of the resolved path.
    try:
        rel = candidate.relative_to(root_resolved)
    except ValueError as e:  # pragma: no cover - ensure_inside_root already guards
        raise PathSecurityError(f"path escapes data root: {relative_path!r}") from e

    input_parts = [p for p in s.replace("\\", "/").split("/") if p]
    resolved_parts = list(rel.parts)
    if len(input_parts) != len(resolved_parts) or any(
        a != b for a, b in zip(input_parts, resolved_parts, strict=True)
    ):
        raise PathSecurityError(
            f"path case mismatch: supplied {relative_path!r}, on disk {rel.as_posix()!r}"
        )

    if not candidate.is_file():
        raise PathSecurityError(f"input path is not a regular file: {relative_path!r}")

    return candidate


def ensure_inside_root(path: Path, root: Path) -> None:
    """Raise :class:`PathSecurityError` if ``path`` is not under ``root``.

    Both arguments must already be absolute. Uses ``Path.resolve()`` internally
    so symlinks cannot smuggle paths out.
    """
    p = path.resolve(strict=False)
    r = root.resolve(strict=False)
    try:
        p.relative_to(r)
    except ValueError as e:
        raise PathSecurityError(f"path {p} is not inside root {r}") from e


def _new_run_id() -> str:
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    # 4 random bytes → 8 base32 chars; trim to 6 (30 bits of entropy).
    nonce = base64.b32encode(os.urandom(4)).decode("ascii").rstrip("=")[:6]
    return f"{ts}-{nonce}"


def is_run_id(s: str) -> bool:
    return bool(_RUN_ID_RE.match(s))


def create_run_dir(tool_name: str, runs_root: Path) -> tuple[str, Path]:
    """Create ``runs_root/<run_id>/artifacts/`` and empty log files.

    Returns ``(run_id, run_dir)``. The directory is guaranteed to be fresh
    (a collision retries with a new id).
    """
    if not tool_name or "/" in tool_name or "\\" in tool_name:
        raise PathSecurityError(f"invalid tool_name: {tool_name!r}")

    runs_root = runs_root.resolve()
    runs_root.mkdir(parents=True, exist_ok=True)

    for _ in range(5):
        run_id = _new_run_id()
        run_dir = runs_root / run_id
        try:
            run_dir.mkdir(parents=True, exist_ok=False)
        except FileExistsError:
            continue
        (run_dir / "artifacts").mkdir(parents=False, exist_ok=False)
        (run_dir / "stdout.log").touch()
        (run_dir / "stderr.log").touch()
        ensure_inside_root(run_dir, runs_root)
        log.debug("created run dir %s for tool=%s", run_dir, tool_name)
        return run_id, run_dir

    raise PathSecurityError("could not generate a unique run id after 5 attempts")
