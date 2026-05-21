"""Docker CLI/daemon probes and optional Docker Desktop auto-start.

PRESTO tools already launch ephemeral ``docker run --rm`` containers per invocation.
This module handles the *host* prerequisite: a responsive Docker daemon (Docker
Desktop on Windows/macOS). It does not keep a long-lived PRESTO container running.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from .logging_setup import phase_logger

log = phase_logger("docker", "presto_mcp.docker_runtime")

_DOCKER_INFO_TIMEOUT_S = 10
_DOCKER_IMAGE_INSPECT_TIMEOUT_S = 15
_PYTHON_DETECT_TIMEOUT_S = 15
_CONTAINER_PYTHON_CANDIDATES = ("python3", "python")
_DEFAULT_IMAGE_PULL_TIMEOUT_S = 900
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


def run_docker_image_inspect(
    docker_bin: str,
    image: str,
    *,
    timeout_s: int = _DOCKER_IMAGE_INSPECT_TIMEOUT_S,
) -> DockerInfoResult:
    """Run ``docker image inspect <image>``. Never raises."""
    try:
        cp = subprocess.run(
            [docker_bin, "image", "inspect", image],
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


def _binary_on_path_in_image(
    docker_bin: str,
    image: str,
    binary: str,
    *,
    timeout_s: int = _PYTHON_DETECT_TIMEOUT_S,
) -> bool:
    """True when ``which <binary>`` succeeds inside a one-off container."""
    try:
        cp = subprocess.run(
            [docker_bin, "run", "--rm", "--network", "none", image, "which", binary],
            check=False,
            capture_output=True,
            stdin=subprocess.DEVNULL,
            timeout=timeout_s,
            shell=False,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False
    return cp.returncode == 0


def detect_container_python(
    docker_bin: str,
    image: str,
    *,
    candidates: tuple[str, ...] = _CONTAINER_PYTHON_CANDIDATES,
) -> str:
    """Pick the first Python shim available in ``image`` (``python3`` before ``python``)."""
    for name in candidates:
        if _binary_on_path_in_image(docker_bin, image, name):
            return name
    log.warning(
        "no %s in image %s; defaulting to python3",
        " or ".join(candidates),
        image,
    )
    return "python3"


def resolve_container_python(
    docker_bin: str,
    image: str,
    explicit: str,
) -> str:
    """Return ``explicit`` when set (must exist in image), else auto-detect."""
    choice = explicit.strip()
    if choice:
        if not _binary_on_path_in_image(docker_bin, image, choice):
            raise ValueError(
                f"PRESTO_PYTHON_BIN={choice!r} is not on PATH inside image {image!r}"
            )
        return choice
    return detect_container_python(docker_bin, image)


def run_docker_pull(
    docker_bin: str,
    image: str,
    *,
    timeout_s: int = _DEFAULT_IMAGE_PULL_TIMEOUT_S,
) -> DockerInfoResult:
    """Run ``docker pull <image>``. Never raises. Streams pull output to stderr."""
    log.info("pulling image (may take several minutes): %s", image)
    try:
        cp = subprocess.run(
            [docker_bin, "pull", image],
            check=False,
            capture_output=False,
            stdin=subprocess.DEVNULL,
            timeout=timeout_s,
            shell=False,
        )
    except subprocess.TimeoutExpired:
        return DockerInfoResult(
            ok=False,
            returncode=-1,
            detail=f"`docker pull {image}` timed out after {timeout_s}s",
        )
    except (FileNotFoundError, OSError) as e:
        return DockerInfoResult(ok=False, returncode=-1, detail=str(e))
    if cp.returncode == 0:
        log.info("pull completed: %s", image)
        return DockerInfoResult(ok=True, returncode=0)
    return DockerInfoResult(
        ok=False,
        returncode=cp.returncode,
        detail=f"`docker pull {image}` failed with exit={cp.returncode}",
    )


def diagnose_docker_image_failure(
    image: str,
    result: DockerInfoResult,
    *,
    pull_attempted: bool = False,
) -> DockerDaemonDiagnosis:
    """Map a missing/failed image probe or pull to an actionable diagnosis."""
    detail = (result.detail or "").strip()
    if pull_attempted:
        return DockerDaemonDiagnosis(
            code="DOCKER_IMAGE_PULL_FAILED",
            summary=f"Failed to pull PRESTO image {image!r}.",
            remediation=(
                f"Run manually: docker pull {image}",
                "Check network access and image name/tag in PRESTO_IMAGE.",
                "Increase PRESTO_PULL_IMAGE_TIMEOUT_SECONDS if the image is large.",
                "Restart presto-mcp after the pull succeeds.",
            ),
            detail=detail or None,
        )
    return DockerDaemonDiagnosis(
        code="DOCKER_IMAGE_MISSING",
        summary=f"PRESTO image {image!r} is not available locally.",
        remediation=(
            f"Run: docker pull {image}",
            "Or set PRESTO_PULL_IMAGE_ON_START=true so presto-mcp pulls on startup.",
            "Verify PRESTO_IMAGE in .env, then restart presto-mcp.",
        ),
        detail=detail or None,
    )


def ensure_presto_image(
    docker_bin: str,
    image: str,
    *,
    pull_if_missing: bool,
    pull_timeout_s: int = _DEFAULT_IMAGE_PULL_TIMEOUT_S,
) -> DockerDaemonDiagnosis | None:
    """Return None when ``image`` is present locally; pull first when configured."""
    inspect = run_docker_image_inspect(docker_bin, image)
    if inspect.ok:
        log.info("image present: %s", image)
        return None

    if not pull_if_missing:
        return diagnose_docker_image_failure(image, inspect)

    pull = run_docker_pull(docker_bin, image, timeout_s=pull_timeout_s)
    if not pull.ok:
        return diagnose_docker_image_failure(image, pull, pull_attempted=True)

    inspect = run_docker_image_inspect(docker_bin, image)
    if inspect.ok:
        log.info("image ready after pull: %s", image)
        return None
    return diagnose_docker_image_failure(image, inspect, pull_attempted=True)


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
                "daemon did not become ready in time (startup wait is capped for MCP "
                "stdio clients — increase PRESTO_AUTO_START_DOCKER_STARTUP_WAIT_SECONDS "
                "or wait for Docker, then click Connect again in Inspector).",
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
    log_progress: bool = False,
) -> DockerInfoResult:
    """Poll ``docker info`` until success or timeout."""
    deadline = time.monotonic() + timeout_s
    last = run_docker_info(docker_bin)
    next_progress = time.monotonic() + 10.0
    while not last.ok and time.monotonic() < deadline:
        if log_progress and time.monotonic() >= next_progress:
            remaining = max(0, int(deadline - time.monotonic()))
            log.info("still waiting for Docker daemon (%ss left)", remaining)
            next_progress = time.monotonic() + 10.0
        time.sleep(poll_interval_s)
        last = run_docker_info(docker_bin)
    return last


def ensure_docker_daemon(
    docker_bin: str,
    *,
    auto_start: bool,
    wait_timeout_s: int = _DEFAULT_AUTO_START_TIMEOUT_S,
    log_progress: bool = False,
) -> DockerDaemonDiagnosis | None:
    """Return None if daemon is healthy; otherwise a structured diagnosis."""
    first = run_docker_info(docker_bin)
    if first.ok:
        log.info("daemon ready")
        return None

    auto_start_attempted = False
    if auto_start and launch_docker_desktop():
        auto_start_attempted = True
        log.info(
            "waiting up to %ss for Docker daemon after auto-start attempt",
            wait_timeout_s,
        )
        first = wait_for_docker_daemon(
            docker_bin,
            timeout_s=wait_timeout_s,
            log_progress=log_progress,
        )

    if first.ok:
        log.info("daemon ready after auto-start")
        return None
    return diagnose_docker_info_failure(first, auto_start_attempted=auto_start_attempted)


__all__ = [
    "DockerDaemonDiagnosis",
    "DockerInfoResult",
    "diagnose_docker_image_failure",
    "diagnose_docker_info_failure",
    "ensure_docker_daemon",
    "detect_container_python",
    "ensure_presto_image",
    "format_startup_failure_banner",
    "resolve_container_python",
    "launch_docker_desktop",
    "resolve_docker_bin",
    "run_docker_image_inspect",
    "run_docker_info",
    "run_docker_pull",
    "wait_for_docker_daemon",
]
