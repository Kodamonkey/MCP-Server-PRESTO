"""Utility tool: validate local environment without running PRESTO.

Returns a structured per-check report. Never raises; failures are captured as
individual ``EnvironmentCheck`` entries. All subprocess calls use ``shell=False``
with explicit argv and a short timeout.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

from ..config import Settings, find_cloud_placeholder_files, get_settings
from ..docker_backend import BackendProtocol
from ..models import (
    EnvironmentCheck,
    EnvironmentCheckStatus,
    RuntimeCheckStatus,
    RuntimeCompatibilityResult,
    ToolReadiness,
    ValidateEnvironmentResult,
)
from ..runtime_checks import collect_runtime_compatibility

log = logging.getLogger("presto_mcp.tools.validate_environment")

_DOCKER_PROBE_TIMEOUT_S = 5
_IMAGE_PROBE_TIMEOUT_S = 10
_STATUS_RANK: dict[EnvironmentCheckStatus, int] = {"OK": 0, "WARN": 1, "ERROR": 2}

# Tool readiness is fail-open: an UNKNOWN probe must not turn into an ERROR.
_RUNTIME_TO_ENV: dict[RuntimeCheckStatus, EnvironmentCheckStatus] = {
    "OK": "OK",
    "WARN": "WARN",
    "ERROR": "ERROR",
    "UNKNOWN": "WARN",
}


def _aggregate(checks: list[EnvironmentCheck]) -> EnvironmentCheckStatus:
    if not checks:
        return "OK"
    worst = max(_STATUS_RANK[c.status] for c in checks)
    for status, rank in _STATUS_RANK.items():
        if rank == worst:
            return status
    return "OK"


def _check_settings_loaded(settings: Settings | None) -> tuple[Settings | None, EnvironmentCheck]:
    try:
        s = settings or get_settings()
    except Exception as e:  # noqa: BLE001
        return None, EnvironmentCheck(
            name="settings.load",
            status="ERROR",
            message=f"failed to load settings: {e}",
            remediation="Check .env and PRESTO_* environment variables.",
        )
    return s, EnvironmentCheck(
        name="settings.load",
        status="OK",
        message=f"image={s.image} data_dir=<set> runs_dir=<set>",
    )


def _check_data_dir(s: Settings) -> list[EnvironmentCheck]:
    checks: list[EnvironmentCheck] = []
    if not s.data_dir.is_dir():
        checks.append(
            EnvironmentCheck(
                name="data_dir.exists",
                status="ERROR",
                message="PRESTO_DATA_DIR does not exist",
                remediation="Create the directory or set PRESTO_DATA_DIR to a valid path.",
            )
        )
        return checks

    checks.append(
        EnvironmentCheck(name="data_dir.exists", status="OK", message="exists")
    )

    has_files = False
    placeholders: list[str] = []
    cloud_placeholders: list[str] = []
    try:
        for p in s.data_dir.iterdir():
            if not p.is_file() or p.name.startswith("."):
                continue
            has_files = True
            try:
                if p.stat().st_size == 0:
                    placeholders.append(p.name)
            except OSError:
                continue
        cloud_placeholders = [p.name for p in find_cloud_placeholder_files(s.data_dir)]
    except OSError as e:
        checks.append(
            EnvironmentCheck(
                name="data_dir.scan",
                status="WARN",
                message=f"could not scan data_dir: {e}",
            )
        )
        return checks

    if not has_files:
        checks.append(
            EnvironmentCheck(
                name="data_dir.has_files",
                status="WARN",
                message="data_dir contains no observation files",
                remediation="Drop at least one .fil/.fits/.sf under PRESTO_DATA_DIR.",
            )
        )
    else:
        checks.append(
            EnvironmentCheck(name="data_dir.has_files", status="OK", message="contains files")
        )

    if placeholders:
        names = ", ".join(placeholders[:5]) + (" ..." if len(placeholders) > 5 else "")
        checks.append(
            EnvironmentCheck(
                name="data_dir.zero_byte_files",
                status="WARN",
                message=f"zero-byte files (likely OneDrive placeholders): {names}",
                remediation=(
                    "In Windows Explorer right-click data/ → 'Always keep on this "
                    "device' and wait for sync to finish."
                ),
            )
        )
    if cloud_placeholders:
        names = ", ".join(cloud_placeholders[:5]) + (
            " ..." if len(cloud_placeholders) > 5 else ""
        )
        checks.append(
            EnvironmentCheck(
                name="data_dir.cloud_placeholders",
                status="WARN",
                message=f"cloud-only files (OneDrive placeholders): {names}",
                remediation=(
                    "In Windows Explorer right-click data/ -> 'Always keep on this "
                    "device' and wait for sync to finish."
                ),
            )
        )
    return checks


def _check_writable_dir(name: str, path: Path) -> EnvironmentCheck:
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return EnvironmentCheck(
            name=f"{name}.writable",
            status="ERROR",
            message=f"cannot create {path}: {e}",
            remediation=f"Set PRESTO_{name.upper()}_DIR to a writable path.",
        )
    return EnvironmentCheck(
        name=f"{name}.writable", status="OK", message="exists / created"
    )


def _check_docker_cli() -> tuple[str | None, list[EnvironmentCheck]]:
    docker = shutil.which("docker")
    if not docker:
        return None, [
            EnvironmentCheck(
                name="docker.cli",
                status="ERROR",
                message="docker CLI not found on PATH",
                remediation="Install Docker Desktop and ensure 'docker' is on PATH.",
            )
        ]
    checks = [
        EnvironmentCheck(name="docker.cli", status="OK", message=docker)
    ]
    try:
        cp = subprocess.run(
            [docker, "--version"],
            check=False,
            capture_output=True,
            stdin=subprocess.DEVNULL,
            timeout=_DOCKER_PROBE_TIMEOUT_S,
            shell=False,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        checks.append(
            EnvironmentCheck(
                name="docker.version",
                status="ERROR",
                message=f"`docker --version` failed: {e}",
                remediation="Reinstall Docker Desktop or repair PATH.",
            )
        )
        return docker, checks
    if cp.returncode != 0:
        checks.append(
            EnvironmentCheck(
                name="docker.version",
                status="ERROR",
                message=f"`docker --version` exit={cp.returncode}",
                remediation="Reinstall Docker Desktop or repair PATH.",
            )
        )
        return docker, checks
    version = (cp.stdout or b"").decode("utf-8", errors="replace").strip()
    checks.append(
        EnvironmentCheck(name="docker.version", status="OK", message=version or "ok")
    )
    return docker, checks


def _check_docker_daemon(docker: str) -> EnvironmentCheck:
    try:
        cp = subprocess.run(
            [docker, "info"],
            check=False,
            capture_output=True,
            stdin=subprocess.DEVNULL,
            timeout=_DOCKER_PROBE_TIMEOUT_S,
            shell=False,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        return EnvironmentCheck(
            name="docker.daemon",
            status="ERROR",
            message=f"`docker info` failed: {e}",
            remediation="Start Docker Desktop / the docker daemon.",
        )
    if cp.returncode != 0:
        stderr = (cp.stderr or b"").decode("utf-8", errors="replace").strip()
        stdout = (cp.stdout or b"").decode("utf-8", errors="replace").strip()
        detail = stderr or stdout or f"exit={cp.returncode}"
        return EnvironmentCheck(
            name="docker.daemon",
            status="ERROR",
            message=f"`docker info` failed: {detail}",
            remediation="Start Docker Desktop / the docker daemon.",
        )
    return EnvironmentCheck(name="docker.daemon", status="OK", message="available")


def _check_image(docker: str, image: str) -> EnvironmentCheck:
    try:
        cp = subprocess.run(
            [docker, "image", "inspect", image],
            check=False,
            capture_output=True,
            stdin=subprocess.DEVNULL,
            timeout=_IMAGE_PROBE_TIMEOUT_S,
            shell=False,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        return EnvironmentCheck(
            name="docker.image",
            status="WARN",
            message=f"image inspect failed: {e}",
            remediation=f"docker pull {image}",
        )
    if cp.returncode != 0:
        return EnvironmentCheck(
            name="docker.image",
            status="WARN",
            message=f"image not present locally: {image}",
            remediation=f"docker pull {image}",
        )
    return EnvironmentCheck(
        name="docker.image", status="OK", message=f"present: {image}"
    )


def _check_policies(s: Settings) -> EnvironmentCheck:
    issues: list[str] = []
    if s.default_cpus <= 0:
        issues.append("default_cpus <= 0")
    if s.default_memory_mb < 512:
        issues.append("default_memory_mb < 512")
    if s.default_timeout_s < 30:
        issues.append("default_timeout_s < 30")
    if s.max_concurrent_runs < 1:
        issues.append("max_concurrent_runs < 1")
    if issues:
        return EnvironmentCheck(
            name="policy.defaults",
            status="WARN",
            message="; ".join(issues),
            remediation="Adjust PRESTO_DEFAULT_CPUS / MEMORY_MB / TIMEOUT_SECONDS.",
        )
    return EnvironmentCheck(
        name="policy.defaults",
        status="OK",
        message=(
            f"cpus={s.default_cpus} memory_mb={s.default_memory_mb} "
            f"timeout_s={s.default_timeout_s} "
            f"max_concurrent_runs={s.max_concurrent_runs}"
        ),
    )


def _readiness_to_check(r: ToolReadiness) -> EnvironmentCheck:
    """Fold one ToolReadiness into an EnvironmentCheck for the flat report."""
    status = _RUNTIME_TO_ENV[r.status]
    if r.status == "OK":
        return EnvironmentCheck(
            name=f"tool_readiness.presto.{r.tool_name}",
            status=status,
            message="all runtime dependencies satisfied",
        )
    bad = [c for c in r.checks if c.status != "OK"]
    detail = "; ".join(f"{c.name}={c.status}" for c in bad) or f"readiness={r.status}"
    remediation = next((c.remediation for c in bad if c.remediation), None)
    return EnvironmentCheck(
        name=f"tool_readiness.presto.{r.tool_name}",
        status=status,
        message=detail,
        remediation=remediation,
    )


def _collect_runtime_compat(
    s: Settings,
    backend: BackendProtocol | None,
    force_refresh: bool,
) -> RuntimeCompatibilityResult | None:
    """Probe image capabilities + per-tool readiness. Never raises."""
    b = backend
    if b is None:
        try:
            from ..docker_backend import DockerBackend

            b = DockerBackend()
        except Exception as e:  # noqa: BLE001
            log.warning("cannot build docker backend for tool readiness: %s", e)
            return None
    try:
        return collect_runtime_compatibility(b, s, force_refresh=force_refresh)
    except Exception as e:  # noqa: BLE001
        log.warning("runtime compatibility collection failed: %s", e)
        return None


def run_validate_environment(
    *,
    check_image: bool = True,
    include_tool_readiness: bool = False,
    force_refresh: bool = False,
    settings: Settings | None = None,
    backend: BackendProtocol | None = None,
) -> ValidateEnvironmentResult:
    checks: list[EnvironmentCheck] = []

    s, settings_check = _check_settings_loaded(settings)
    checks.append(settings_check)
    if s is None:
        return ValidateEnvironmentResult(status=_aggregate(checks), checks=checks)

    checks.extend(_check_data_dir(s))
    checks.append(_check_writable_dir("runs", s.runs_dir))
    checks.append(_check_writable_dir("outputs", s.outputs_dir))
    checks.append(_check_writable_dir("logs", s.logs_dir))

    docker, docker_checks = _check_docker_cli()
    checks.extend(docker_checks)

    daemon_ok = False
    if docker is not None and all(c.status == "OK" for c in docker_checks):
        daemon_check = _check_docker_daemon(docker)
        checks.append(daemon_check)
        daemon_ok = daemon_check.status == "OK"

    if docker is not None and daemon_ok and check_image:
        checks.append(_check_image(docker, s.image))

    checks.append(_check_policies(s))

    runtime_compat: RuntimeCompatibilityResult | None = None
    if include_tool_readiness:
        if docker is not None and daemon_ok:
            runtime_compat = _collect_runtime_compat(s, backend, force_refresh)
        if runtime_compat is not None:
            for r in runtime_compat.tool_readiness:
                checks.append(_readiness_to_check(r))
        else:
            checks.append(
                EnvironmentCheck(
                    name="tool_readiness",
                    status="WARN",
                    message=(
                        "tool readiness not probed (Docker daemon or PRESTO "
                        "image unavailable)"
                    ),
                    remediation=(
                        "Ensure Docker is running and the PRESTO image is pulled, "
                        "then re-run with include_tool_readiness=true."
                    ),
                )
            )

    return ValidateEnvironmentResult(
        status=_aggregate(checks),
        checks=checks,
        runtime_compatibility=runtime_compat,
    )


__all__ = ["run_validate_environment"]
