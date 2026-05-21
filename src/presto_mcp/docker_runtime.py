"""Docker CLI/daemon probes and optional Docker Desktop auto-start.

PRESTO tools already launch ephemeral ``docker run --rm`` containers per invocation.
This module handles the *host* prerequisite: a responsive Docker daemon (Docker
Desktop on Windows/macOS). It does not keep a long-lived PRESTO container running.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("presto_mcp.docker_runtime")

_DOCKER_INFO_TIMEOUT_S = 10
_DEFAULT_AUTO_START_TIMEOUT_S = 120
_POLL_INTERVAL_S = 2.0

# Substrings from ``docker info`` when the engine pipe/socket is missing.
_DAEMON_DOWN_MARKERS = (
    "cannot find the file specified",
    "no such file or directory",
    "connection refused",
    "is the docker daemon running",
    "failed to connect to the docker api",
    "error during connect",
    "dockerdesktoplinuxengine",
)


@dataclass(frozen=True)
class DockerInfoResult:
    """Outcome of ``docker info`` (or equivalent probe)."""

    ok: bool
    returncode: int
    detail: str | None = None


@dataclass(frozen=True)
class DockerDaemonDiagnosis:
    """Structured daemon failure for startup errors and validate_environment."""

    code: str
    summary: str
    remediation: tuple[str, ...]
    detail: str | None = None


def resolve_docker_bin(explicit: str | None = None) -> str | None:
    return explicit or shutil.which("docker")


def run_docker_info(docker_bin: str, *, timeout_s: int = _DOCKER_INFO_TIMEOUT_S) -> DockerInfoResult:
    """Run ``docker info``. Never raises."""
    try:
        cp = subprocess.run(
            [docker_bin, "info"],
            check=False,
            capture_output=True,
            stdin=subprocess.DEVNULL,
            timeout=timeout_s,
            shell=False,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        return DockerInfoResult(ok=False, returncode=-1, detail=str(e))
    stderr = (cp.stderr or b"").decode("utf-8", errors="replace").strip()
    stdout = (cp.stdout or b"").decode("utf-8", errors="replace").strip()
    detail = stderr or stdout or None
    return DockerInfoResult(ok=cp.returncode == 0, returncode=cp.returncode, detail=detail)


def diagnose_docker_info_failure(
    result: DockerInfoResult,
    *,
    auto_start_attempted: bool = False,
) -> DockerDaemonDiagnosis:
    """Map a failed ``docker info`` probe to an actionable diagnosis."""
    detail = (result.detail or "").strip()
    lower = detail.lower()

    if "command not found" in lower or isinstance(result.detail, FileNotFoundError):
        return DockerDaemonDiagnosis(
            code="DOCKER_CLI_MISSING",
            summary="Docker CLI is not installed or not on PATH.",
            remediation=(
                "Install Docker Desktop from https://www.docker.com/products/docker-desktop/",
                "Restart the terminal after installation so `docker` is on PATH.",
                "Re-run: uv run --directory . python -m presto_mcp.server",
            ),
            detail=detail or None,
        )

    if any(marker in lower for marker in _DAEMON_DOWN_MARKERS) or result.returncode != 0:
        steps: list[str] = [
            "Start Docker Desktop and wait until it shows Running (whale icon steady).",
            "In PowerShell run `docker info` — it must succeed before the MCP server starts.",
            "Then reconnect MCP Inspector or restart the presto MCP entry in Cursor.",
        ]
        if sys.platform == "win32":
            steps.insert(
                1,
                "Or set PRESTO_AUTO_START_DOCKER=true in .env so presto-mcp tries to "
                "launch Docker Desktop on startup (first start can take 1–2 minutes).",
            )
        if auto_start_attempted:
            steps.insert(
                0,
                "presto-mcp attempted to start Docker Desktop automatically but the "
                "daemon did not become ready in time.",
            )
        return DockerDaemonDiagnosis(
            code="DOCKER_DAEMON_DOWN",
            summary="Docker is installed but the engine/daemon is not running.",
            remediation=tuple(steps),
            detail=detail or f"exit={result.returncode}",
        )

    return DockerDaemonDiagnosis(
        code="DOCKER_INFO_FAILED",
        summary="`docker info` failed for an unknown reason.",
        remediation=(
            "Run `docker info` in a terminal and fix the reported error.",
            "Restart Docker Desktop, then restart presto-mcp.",
        ),
        detail=detail or f"exit={result.returncode}",
    )


def format_startup_failure_banner(
    diagnosis: DockerDaemonDiagnosis,
    *,
    context: str = "startup health check",
) -> str:
    """Multi-line message for logs/stderr when the server refuses to boot."""
    lines = [
        "",
        "=" * 72,
        "PRESTO MCP — cannot start (" + context + ")",
        "=" * 72,
        f"Problem : {diagnosis.summary}",
        f"Code    : {diagnosis.code}",
    ]
    if diagnosis.detail:
        lines.append(f"Detail  : {diagnosis.detail[:500]}")
    lines.append("")
    lines.append("What to do:")
    for i, step in enumerate(diagnosis.remediation, start=1):
        lines.append(f"  {i}. {step}")
    lines.extend(
        [
            "",
            "Note: each PRESTO tool already runs `docker run --rm` with the configured",
            "image. This check only ensures the Docker *engine* is up — not a separate",
            "long-lived container.",
            "",
            "Bypass (Inspector UI only, tools will fail until Docker works):",
            "  PRESTO_SKIP_HEALTHCHECK=true",
            "=" * 72,
            "",
        ]
    )
    return "\n".join(lines)


def _windows_docker_desktop_exe() -> Path | None:
    roots = [
        os.environ.get("PROGRAMFILES"),
        os.environ.get("PROGRAMFILES(X86)"),
    ]
    for root in roots:
        if not root:
            continue
        candidate = Path(root) / "Docker" / "Docker" / "Docker Desktop.exe"
        if candidate.is_file():
            return candidate
    return None


def _macos_docker_app() -> Path | None:
    app = Path("/Applications/Docker.app")
    if app.is_dir():
        return app
    return None


def launch_docker_desktop() -> bool:
    """Best-effort start of Docker Desktop. Returns True if a launch was attempted."""
    if sys.platform == "win32":
        exe = _windows_docker_desktop_exe()
        if exe is None:
            log.warning("Docker Desktop.exe not found under Program Files")
            return False
        log.info("launching Docker Desktop: %s", exe)
        subprocess.Popen(
            [str(exe)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            shell=False,
        )
        return True

    if sys.platform == "darwin":
        app = _macos_docker_app()
        if app is None:
            log.warning("Docker.app not found under /Applications")
            return False
        open_bin = shutil.which("open") or "/usr/bin/open"
        log.info("launching Docker via: %s -a Docker", open_bin)
        subprocess.Popen(
            [open_bin, "-a", "Docker"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            shell=False,
        )
        return True

    # Linux: only attempt passwordless systemctl when available.
    systemctl = shutil.which("systemctl")
    if systemctl is None:
        return False
    log.info("attempting: systemctl start docker")
    try:
        subprocess.run(
            [systemctl, "start", "docker"],
            check=False,
            capture_output=True,
            stdin=subprocess.DEVNULL,
            timeout=15,
            shell=False,
        )
    except (subprocess.TimeoutExpired, OSError) as e:
        log.warning("systemctl start docker failed: %s", e)
        return False
    return True


def wait_for_docker_daemon(
    docker_bin: str,
    *,
    timeout_s: int = _DEFAULT_AUTO_START_TIMEOUT_S,
    poll_interval_s: float = _POLL_INTERVAL_S,
) -> DockerInfoResult:
    """Poll ``docker info`` until success or timeout."""
    deadline = time.monotonic() + timeout_s
    last = run_docker_info(docker_bin)
    while not last.ok and time.monotonic() < deadline:
        time.sleep(poll_interval_s)
        last = run_docker_info(docker_bin)
    return last


def ensure_docker_daemon(
    docker_bin: str,
    *,
    auto_start: bool,
    wait_timeout_s: int = _DEFAULT_AUTO_START_TIMEOUT_S,
) -> DockerDaemonDiagnosis | None:
    """Return None if daemon is healthy; otherwise a structured diagnosis."""
    first = run_docker_info(docker_bin)
    if first.ok:
        return None

    auto_start_attempted = False
    if auto_start and launch_docker_desktop():
        auto_start_attempted = True
        log.info(
            "waiting up to %ss for Docker daemon after auto-start attempt",
            wait_timeout_s,
        )
        first = wait_for_docker_daemon(docker_bin, timeout_s=wait_timeout_s)

    if first.ok:
        return None
    return diagnose_docker_info_failure(first, auto_start_attempted=auto_start_attempted)


__all__ = [
    "DockerDaemonDiagnosis",
    "DockerInfoResult",
    "diagnose_docker_info_failure",
    "ensure_docker_daemon",
    "format_startup_failure_banner",
    "launch_docker_desktop",
    "resolve_docker_bin",
    "run_docker_info",
    "wait_for_docker_daemon",
]
