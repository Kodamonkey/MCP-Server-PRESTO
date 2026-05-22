"""Environment-driven configuration + startup health check.

Loads settings from environment (or a sibling ``.env``) once, exposes a frozen
``Settings`` instance via :func:`get_settings`. Settings are intentionally
immutable so tests can build a fresh instance with overrides without leaking
state.
"""

from __future__ import annotations

import logging
import os
import stat
import sys
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

from .docker_runtime import (
    DockerDaemonDiagnosis,
    DockerInfoResult,
    diagnose_docker_info_failure,
    ensure_docker_daemon,
    ensure_presto_image,
    format_startup_failure_banner,
    resolve_container_python,
    resolve_docker_bin,
)

log = logging.getLogger("presto_mcp.config")

_RESOLVED_CONTAINER_PYTHON: str | None = None
_DEFAULT_CONTAINER_PYTHON = "python3"


def get_resolved_container_python(settings: Settings) -> str:
    """Python binary for container scripts; set at startup or via env."""
    if settings.python_bin.strip():
        return settings.python_bin.strip()
    if _RESOLVED_CONTAINER_PYTHON is not None:
        return _RESOLVED_CONTAINER_PYTHON
    return _DEFAULT_CONTAINER_PYTHON


def set_resolved_container_python(value: str) -> None:
    global _RESOLVED_CONTAINER_PYTHON
    _RESOLVED_CONTAINER_PYTHON = value


def clear_resolved_container_python() -> None:
    global _RESOLVED_CONTAINER_PYTHON
    _RESOLVED_CONTAINER_PYTHON = None

REPO_ROOT = Path(__file__).resolve().parents[2]

_RECALL_ON_OPEN = 0x00040000
_RECALL_ON_DATA_ACCESS = 0x00400000
_CLOUD_PLACEHOLDER_FLAGS = (
    getattr(stat, "FILE_ATTRIBUTE_OFFLINE", 0x00001000),
    _RECALL_ON_OPEN,
    _RECALL_ON_DATA_ACCESS,
)


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_path(name: str, default_rel: str) -> Path:
    raw = os.environ.get(name, default_rel)
    p = Path(raw)
    if not p.is_absolute():
        p = (REPO_ROOT / p).resolve()
    return p


def _env_bool_or_none(name: str) -> bool | None:
    raw = os.environ.get(name)
    if raw is None:
        return None
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _default_auto_start_docker() -> bool:
    """Windows/macOS: try to launch Docker Desktop when the daemon is down."""
    return sys.platform in ("win32", "darwin")


def _env_int_min(name: str, default: int, minimum: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as e:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from e
    if value < minimum:
        raise ValueError(f"{name} must be >= {minimum}, got {value}")
    return value


@dataclass(frozen=True)
class Settings:
    """Runtime configuration. All paths are absolute and resolved."""

    image: str
    data_dir: Path
    runs_dir: Path
    outputs_dir: Path
    default_cpus: float
    default_memory_mb: int
    default_timeout_s: int
    network: str
    skip_healthcheck: bool
    auto_start_docker: bool = False
    auto_start_docker_timeout_s: int = 120
    auto_start_docker_startup_wait_s: int = 45
    pull_image_on_start: bool = True
    pull_image_timeout_s: int = 900
    python_bin: str = ""
    max_concurrent_runs: int = 1
    tool_profile: str = "all"

    def resolved_python_bin(self) -> str:
        """Python executable for in-container scripts (e.g. waterfaller headless)."""
        return get_resolved_container_python(self)

    def with_overrides(self, **kwargs: object) -> Settings:
        """Return a copy with selected fields replaced (test helper)."""
        return replace(self, **kwargs)  # type: ignore[arg-type]


def _load_from_env() -> Settings:
    # Load .env from repo root if present. Real env vars win.
    load_dotenv(REPO_ROOT / ".env", override=False)

    return Settings(
        image=os.environ.get("PRESTO_IMAGE", "alex88ridolfi/presto5:png"),
        data_dir=_env_path("PRESTO_DATA_DIR", "./data"),
        runs_dir=_env_path("PRESTO_RUNS_DIR", "./runs"),
        outputs_dir=_env_path("PRESTO_OUTPUTS_DIR", "./outputs"),
        default_cpus=float(os.environ.get("PRESTO_DEFAULT_CPUS", "4")),
        default_memory_mb=int(os.environ.get("PRESTO_DEFAULT_MEMORY_MB", "8192")),
        default_timeout_s=int(os.environ.get("PRESTO_DEFAULT_TIMEOUT_SECONDS", "1800")),
        network=os.environ.get("PRESTO_NETWORK", "none"),
        skip_healthcheck=_env_bool("PRESTO_SKIP_HEALTHCHECK", False),
        auto_start_docker=(
            _auto
            if (_auto := _env_bool_or_none("PRESTO_AUTO_START_DOCKER")) is not None
            else _default_auto_start_docker()
        ),
        auto_start_docker_timeout_s=_env_int_min(
            "PRESTO_AUTO_START_DOCKER_TIMEOUT_SECONDS", 120, 15
        ),
        auto_start_docker_startup_wait_s=_env_int_min(
            "PRESTO_AUTO_START_DOCKER_STARTUP_WAIT_SECONDS", 45, 10
        ),
        pull_image_on_start=_env_bool("PRESTO_PULL_IMAGE_ON_START", True),
        pull_image_timeout_s=_env_int_min(
            "PRESTO_PULL_IMAGE_TIMEOUT_SECONDS", 900, 60
        ),
        python_bin=os.environ.get("PRESTO_PYTHON_BIN", "").strip(),
        max_concurrent_runs=_env_int_min("PRESTO_MAX_CONCURRENT_RUNS", 2, 1),
        tool_profile=os.environ.get("PRESTO_TOOL_PROFILE", "all").strip().lower(),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached accessor. Call this from runtime code; pass overrides in tests."""
    return _load_from_env()


def ensure_runtime_dirs(s: Settings) -> None:
    """Create runs/outputs if missing. ``data/`` must already exist."""
    for d in (s.runs_dir, s.outputs_dir):
        d.mkdir(parents=True, exist_ok=True)


def has_cloud_placeholder_attributes(path: Path) -> bool:
    """Return true for OneDrive/cloud files not fully present on disk."""
    try:
        attrs = getattr(path.stat(), "st_file_attributes", 0)
    except OSError:
        return False
    return any(attrs & flag for flag in _CLOUD_PLACEHOLDER_FLAGS)


def find_cloud_placeholder_files(data_dir: Path) -> list[Path]:
    placeholders: list[Path] = []
    try:
        children = list(data_dir.iterdir())
    except OSError:
        return placeholders
    for p in children:
        if p.name.startswith("."):
            continue
        try:
            if p.is_file() and has_cloud_placeholder_attributes(p):
                placeholders.append(p)
        except OSError:
            continue
    return placeholders


class HealthCheckError(RuntimeError):
    """Startup health check failed; server must not boot."""

    def __init__(
        self,
        summary: str,
        *,
        code: str = "HEALTH_CHECK_FAILED",
        remediation: tuple[str, ...] = (),
        detail: str | None = None,
    ) -> None:
        self.code = code
        self.summary = summary
        self.remediation = remediation
        self.detail = detail
        super().__init__(summary)

    @classmethod
    def from_docker_diagnosis(cls, diagnosis: DockerDaemonDiagnosis) -> HealthCheckError:
        return cls(
            diagnosis.summary,
            code=diagnosis.code,
            remediation=diagnosis.remediation,
            detail=diagnosis.detail,
        )

    def docker_diagnosis(self) -> DockerDaemonDiagnosis | None:
        if not self.remediation:
            return None
        return DockerDaemonDiagnosis(
            code=self.code,
            summary=self.summary,
            remediation=self.remediation,
            detail=self.detail,
        )


def format_health_check_failure(exc: HealthCheckError) -> str:
    """User-visible banner for stderr (MCP Inspector / terminal)."""
    diagnosis = exc.docker_diagnosis()
    if diagnosis is not None:
        return format_startup_failure_banner(diagnosis)
    return format_startup_failure_banner(
        DockerDaemonDiagnosis(
            code=exc.code,
            summary=exc.summary,
            remediation=exc.remediation or (exc.summary,),
            detail=exc.detail,
        ),
    )


def run_health_check(s: Settings, docker_bin: str | None = None) -> None:
    """Validate the environment before the server accepts connections.

    Checks:
      * ``data_dir`` exists and contains at least one file.
      * No file under ``data_dir`` is 0 bytes (OneDrive placeholder detection).
      * ``docker`` is on PATH and the daemon responds to ``docker info``.
      * ``PRESTO_IMAGE`` is present locally (optional auto-``docker pull`` on start).
    """
    if s.skip_healthcheck:
        log.warning("health check skipped (PRESTO_SKIP_HEALTHCHECK=true)")
        return

    log.info("health check: data_dir %s", s.data_dir)

    if not s.data_dir.is_dir():
        raise HealthCheckError(
            f"PRESTO_DATA_DIR does not exist: {s.data_dir}",
            code="DATA_DIR_MISSING",
            remediation=(
                f"Create {s.data_dir} or set PRESTO_DATA_DIR to a valid path.",
                "Re-run: uv run --directory . python -m presto_mcp.server",
            ),
        )

    placeholders: list[Path] = []
    cloud_placeholders: list[Path] = []
    has_observation_data = False
    for p in s.data_dir.iterdir():
        if not p.is_file():
            continue
        # .gitkeep and other dotfiles are repo scaffolding, not telescope data.
        if p.name.startswith("."):
            continue
        has_observation_data = True
        try:
            st = p.stat()
            if st.st_size == 0:
                placeholders.append(p)
            if has_cloud_placeholder_attributes(p):
                cloud_placeholders.append(p)
        except OSError as e:
            raise HealthCheckError(f"Cannot stat data file {p}: {e}") from e

    if not has_observation_data:
        log.warning(
            "data_dir %s contains no observation files; tools will reject inputs.",
            s.data_dir,
        )

    if placeholders:
        names = ", ".join(p.name for p in placeholders)
        raise HealthCheckError(
            f"Zero-byte data files (likely OneDrive placeholders): {names}",
            code="DATA_ONEDRIVE_PLACEHOLDER",
            remediation=(
                "In Windows Explorer, right-click data/ → 'Always keep on this device'.",
                "Wait until files show a real size (not 0 bytes), then restart presto-mcp.",
            ),
            detail=names,
        )

    if cloud_placeholders:
        names = ", ".join(p.name for p in cloud_placeholders)
        raise HealthCheckError(
            f"Cloud-only data files (OneDrive placeholders): {names}",
            code="DATA_ONEDRIVE_CLOUD_ONLY",
            remediation=(
                "In Windows Explorer, right-click data/ → 'Always keep on this device'.",
                "Wait for sync to finish, then restart presto-mcp.",
            ),
            detail=names,
        )

    log.info("health check: observation files ok")

    log.info("health check: docker daemon")
    docker = resolve_docker_bin(docker_bin)
    if not docker:
        raise HealthCheckError.from_docker_diagnosis(
            diagnose_docker_info_failure(
                DockerInfoResult(
                    ok=False,
                    returncode=-1,
                    detail="docker CLI not found on PATH",
                )
            )
        )

    # Cap wait at startup so MCP stdio clients (Inspector/Cursor) are not left
    # idle for minutes before the process begins reading JSON-RPC from stdin.
    startup_wait = min(
        s.auto_start_docker_timeout_s,
        s.auto_start_docker_startup_wait_s,
    )
    diagnosis = ensure_docker_daemon(
        docker,
        auto_start=s.auto_start_docker,
        wait_timeout_s=startup_wait,
        log_progress=True,
    )
    if diagnosis is not None:
        raise HealthCheckError.from_docker_diagnosis(diagnosis)

    log.info("health check: docker daemon ok")
    log.info("health check: image %s", s.image)
    image_diagnosis = ensure_presto_image(
        docker,
        s.image,
        pull_if_missing=s.pull_image_on_start,
        pull_timeout_s=s.pull_image_timeout_s,
    )
    if image_diagnosis is not None:
        raise HealthCheckError.from_docker_diagnosis(image_diagnosis)

    log.info("health check: image ok")

    try:
        py = resolve_container_python(docker, s.image, s.python_bin)
    except ValueError as e:
        raise HealthCheckError(
            str(e),
            code="CONTAINER_PYTHON_MISSING",
            remediation=(
                "Set PRESTO_PYTHON_BIN to python3 or python (whichever exists in PRESTO_IMAGE).",
                f"Probe manually: docker run --rm {s.image} which python3",
                "Restart presto-mcp after fixing .env.",
            ),
        ) from e
    set_resolved_container_python(py)
    if s.python_bin.strip():
        log.info("health check: container python %s (PRESTO_PYTHON_BIN)", py)
    else:
        log.info("health check: container python %s (auto-detected)", py)

    log.info("health check passed")
