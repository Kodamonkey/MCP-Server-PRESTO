"""Unit tests for docker_runtime probes and diagnostics."""

from __future__ import annotations

from unittest.mock import patch

from presto_mcp.docker_runtime import (
    DockerInfoResult,
    diagnose_docker_info_failure,
    ensure_docker_daemon,
    format_startup_failure_banner,
)


def test_diagnose_daemon_down_windows_pipe() -> None:
    result = DockerInfoResult(
        ok=False,
        returncode=1,
        detail=(
            "failed to connect to the docker API at "
            "npipe:////./pipe/dockerDesktopLinuxEngine"
        ),
    )
    diagnosis = diagnose_docker_info_failure(result)
    assert diagnosis.code == "DOCKER_DAEMON_DOWN"
    assert "engine" in diagnosis.summary.lower()
    assert len(diagnosis.remediation) >= 2


def test_format_startup_banner_includes_code_and_steps() -> None:
    diagnosis = diagnose_docker_info_failure(
        DockerInfoResult(ok=False, returncode=1, detail="daemon down")
    )
    banner = format_startup_failure_banner(diagnosis)
    assert "DOCKER_DAEMON_DOWN" in banner
    assert "What to do:" in banner
    assert "PRESTO_SKIP_HEALTHCHECK" in banner


def test_ensure_docker_daemon_ok_skips_launch() -> None:
    with patch(
        "presto_mcp.docker_runtime.run_docker_info",
        return_value=DockerInfoResult(ok=True, returncode=0),
    ):
        assert ensure_docker_daemon("docker", auto_start=True) is None


def test_ensure_docker_daemon_auto_start_still_fails() -> None:
    with (
        patch(
            "presto_mcp.docker_runtime.run_docker_info",
            return_value=DockerInfoResult(ok=False, returncode=1, detail="daemon down"),
        ),
        patch("presto_mcp.docker_runtime.launch_docker_desktop", return_value=True),
        patch("presto_mcp.docker_runtime.wait_for_docker_daemon") as wait_mock,
    ):
        wait_mock.return_value = DockerInfoResult(
            ok=False, returncode=1, detail="still down"
        )
        diagnosis = ensure_docker_daemon("docker", auto_start=True, wait_timeout_s=4)
    assert diagnosis is not None
    assert diagnosis.code == "DOCKER_DAEMON_DOWN"
    assert "automatically" in diagnosis.remediation[0].lower()
