"""Unit tests for config.py startup health check."""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import patch

import pytest

from presto_mcp.config import (
    HealthCheckError,
    Settings,
    _env_int_min,
    run_health_check,
    warn_if_oversubscribed,
)
from presto_mcp.docker_runtime import (
    DockerInfoResult,
    diagnose_docker_image_failure,
    diagnose_docker_info_failure,
)


def _settings(tmp_path: Path, **overrides: object) -> Settings:
    base = dict(
        image="alex88ridolfi/presto5:png",
        data_dir=(tmp_path / "data").resolve(),
        runs_dir=(tmp_path / "runs").resolve(),
        outputs_dir=(tmp_path / "outputs").resolve(),
        default_cpus=2.0,
        default_memory_mb=1024,
        default_timeout_s=60,
        network="none",
        skip_healthcheck=False,
    )
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def test_env_int_min_uses_default_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PRESTO_TEST_INT", raising=False)
    assert _env_int_min("PRESTO_TEST_INT", default=2, minimum=1) == 2


def test_env_int_min_reads_valid_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRESTO_TEST_INT", "5")
    assert _env_int_min("PRESTO_TEST_INT", default=2, minimum=1) == 5


def test_env_int_min_rejects_non_integer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRESTO_TEST_INT", "notanint")
    with pytest.raises(ValueError, match="must be an integer"):
        _env_int_min("PRESTO_TEST_INT", default=2, minimum=1)


def test_env_int_min_rejects_below_minimum(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRESTO_TEST_INT", "0")
    with pytest.raises(ValueError, match="must be >= 1"):
        _env_int_min("PRESTO_TEST_INT", default=2, minimum=1)


def test_oversubscription_warns(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    cpu_count = 4
    settings = _settings(tmp_path, max_concurrent_runs=8, default_cpus=4.0)
    with (
        patch("presto_mcp.config.os.cpu_count", return_value=cpu_count),
        caplog.at_level(logging.WARNING, logger="presto_mcp.config"),
    ):
        msg = warn_if_oversubscribed(settings)
    assert msg is not None
    assert "oversubscribe" in msg
    assert any("oversubscribe" in r.message for r in caplog.records)


def test_balanced_concurrency_does_not_warn(tmp_path: Path) -> None:
    settings = _settings(tmp_path, max_concurrent_runs=2, default_cpus=2.0)
    with patch("presto_mcp.config.os.cpu_count", return_value=8):
        assert warn_if_oversubscribed(settings) is None


def test_oversubscription_no_cpu_count_is_silent(tmp_path: Path) -> None:
    settings = _settings(tmp_path, max_concurrent_runs=99, default_cpus=99.0)
    with patch("presto_mcp.config.os.cpu_count", return_value=None):
        assert warn_if_oversubscribed(settings) is None


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
