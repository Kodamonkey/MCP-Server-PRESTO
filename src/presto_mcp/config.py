"""Environment-driven configuration + startup health check.

Loads settings from environment (or a sibling ``.env``) once, exposes a frozen
``Settings`` instance via :func:`get_settings`. Settings are intentionally
immutable so tests can build a fresh instance with overrides without leaking
state.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

log = logging.getLogger("presto_mcp.config")

REPO_ROOT = Path(__file__).resolve().parents[2]


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


@dataclass(frozen=True)
class Settings:
    """Runtime configuration. All paths are absolute and resolved."""

    image: str
    data_dir: Path
    runs_dir: Path
    outputs_dir: Path
    logs_dir: Path
    default_cpus: float
    default_memory_mb: int
    default_timeout_s: int
    network: str
    skip_healthcheck: bool

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
        logs_dir=_env_path("PRESTO_LOGS_DIR", "./logs"),
        default_cpus=float(os.environ.get("PRESTO_DEFAULT_CPUS", "4")),
        default_memory_mb=int(os.environ.get("PRESTO_DEFAULT_MEMORY_MB", "8192")),
        default_timeout_s=int(os.environ.get("PRESTO_DEFAULT_TIMEOUT_SECONDS", "1800")),
        network=os.environ.get("PRESTO_NETWORK", "none"),
        skip_healthcheck=_env_bool("PRESTO_SKIP_HEALTHCHECK", False),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached accessor. Call this from runtime code; pass overrides in tests."""
    return _load_from_env()


def ensure_runtime_dirs(s: Settings) -> None:
    """Create runs/outputs/logs if missing. ``data/`` must already exist."""
    for d in (s.runs_dir, s.outputs_dir, s.logs_dir):
        d.mkdir(parents=True, exist_ok=True)


class HealthCheckError(RuntimeError):
    """Startup health check failed; server must not boot."""


def run_health_check(s: Settings, docker_bin: str | None = None) -> None:
    """Validate the environment before the server accepts connections.

    Checks:
      * ``data_dir`` exists and contains at least one file.
      * No file under ``data_dir`` is 0 bytes (OneDrive placeholder detection).
      * ``docker`` is on PATH and responds to ``--version``.
    """
    if s.skip_healthcheck:
        log.warning("PRESTO_SKIP_HEALTHCHECK=true; bypassing startup health check.")
        return

    if not s.data_dir.is_dir():
        raise HealthCheckError(
            f"PRESTO_DATA_DIR does not exist: {s.data_dir}. "
            f"Create it or set PRESTO_DATA_DIR to a valid path."
        )

    placeholders: list[Path] = []
    has_observation_data = False
    for p in s.data_dir.iterdir():
        if not p.is_file():
            continue
        # .gitkeep and other dotfiles are repo scaffolding, not telescope data.
        if p.name.startswith("."):
            continue
        has_observation_data = True
        try:
            if p.stat().st_size == 0:
                placeholders.append(p)
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
            f"Zero-byte data files detected (likely OneDrive cloud-only placeholders): "
            f"{names}. In Windows Explorer, right-click data/ → 'Always keep on this "
            f"device' and wait for sync to finish."
        )

    docker = docker_bin or shutil.which("docker")
    if not docker:
        raise HealthCheckError(
            "docker CLI not found on PATH. Install Docker Desktop and ensure 'docker' is "
            "callable from this shell."
        )

    try:
        subprocess.run(
            [docker, "--version"],
            check=True,
            capture_output=True,
            timeout=10,
            shell=False,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as e:
        raise HealthCheckError(f"`docker --version` failed: {e}") from e
