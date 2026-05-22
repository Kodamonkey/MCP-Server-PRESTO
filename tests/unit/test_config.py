"""Unit tests for config.py startup health check."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from presto_mcp.config import HealthCheckError, Settings, run_health_check
from presto_mcp.docker_runtime import (
    DockerInfoResult,
    diagnose_docker_image_failure,
    diagnose_docker_info_failure,
)


def test_health_check_ignores_dotfiles_in_data_dir(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    (data / ".gitkeep").write_bytes(b"")
    (data / "sample.fil").write_bytes(b"\x00" * 16)

    settings = Settings(
        image="alex88ridolfi/presto5:png",
        data_dir=data.resolve(),
        runs_dir=(tmp_path / "runs").resolve(),
        outputs_dir=(tmp_path / "outputs").resolve(),
        default_cpus=2.0,
        default_memory_mb=1024,
        default_timeout_s=60,
        network="none",
        skip_healthcheck=False,
    )

    with (
        patch("presto_mcp.config.ensure_docker_daemon", return_value=None),
        patch("presto_mcp.config.ensure_presto_image", return_value=None),
        patch("presto_mcp.config.resolve_container_python", return_value="python3"),
    ):
        run_health_check(settings, docker_bin="docker")


def test_health_check_rejects_zero_byte_observation_file(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    (data / "placeholder.fil").write_bytes(b"")

    settings = Settings(
        image="alex88ridolfi/presto5:png",
        data_dir=data.resolve(),
        runs_dir=(tmp_path / "runs").resolve(),
        outputs_dir=(tmp_path / "outputs").resolve(),
        default_cpus=2.0,
        default_memory_mb=1024,
        default_timeout_s=60,
        network="none",
        skip_healthcheck=False,
    )

    with pytest.raises(HealthCheckError, match="placeholder.fil"):
        run_health_check(settings, docker_bin="docker")


def test_health_check_rejects_unavailable_docker_daemon(tmp_path: Path) -> None:
    """Failed docker info surfaces a structured HealthCheckError."""
    data = tmp_path / "data"
    data.mkdir()
    (data / "sample.fil").write_bytes(b"\x00" * 16)

    settings = Settings(
        image="alex88ridolfi/presto5:png",
        data_dir=data.resolve(),
        runs_dir=(tmp_path / "runs").resolve(),
        outputs_dir=(tmp_path / "outputs").resolve(),
        default_cpus=2.0,
        default_memory_mb=1024,
        default_timeout_s=60,
        network="none",
        skip_healthcheck=False,
    )

    with (
        patch(
            "presto_mcp.config.ensure_docker_daemon",
            return_value=diagnose_docker_info_failure(
                DockerInfoResult(ok=False, returncode=1, detail="daemon down")
            ),
        ),
        patch("presto_mcp.config.ensure_presto_image", return_value=None),
        patch("presto_mcp.config.resolve_container_python", return_value="python3"),
        pytest.raises(HealthCheckError, match="engine"),
    ):
        run_health_check(settings, docker_bin="docker")


def test_health_check_error_has_remediation_steps(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    (data / "sample.fil").write_bytes(b"\x00" * 16)

    settings = Settings(
        image="alex88ridolfi/presto5:png",
        data_dir=data.resolve(),
        runs_dir=(tmp_path / "runs").resolve(),
        outputs_dir=(tmp_path / "outputs").resolve(),
        default_cpus=2.0,
        default_memory_mb=1024,
        default_timeout_s=60,
        network="none",
        skip_healthcheck=False,
        auto_start_docker=False,
    )

    image_diagnosis = diagnose_docker_image_failure(
        "alex88ridolfi/presto5:png",
        DockerInfoResult(ok=False, returncode=1, detail="not found"),
    )

    with (
        patch("presto_mcp.config.ensure_docker_daemon", return_value=None),
        patch("presto_mcp.config.ensure_presto_image", return_value=image_diagnosis),
        patch("presto_mcp.config.resolve_container_python", return_value="python3"),
        pytest.raises(HealthCheckError) as exc_info,
    ):
        run_health_check(settings, docker_bin="docker")

    err = exc_info.value
    assert err.code == "DOCKER_IMAGE_MISSING"
    assert err.remediation
