"""Unit tests for presto_mcp.runtime_checks (capability probes + readiness)."""

from __future__ import annotations

from pathlib import Path

import pytest

from presto_mcp.config import Settings
from presto_mcp.models import BackendResult, DockerInvocation, RunStatus
from presto_mcp.runtime_checks import (
    check_binary_available,
    check_binary_help,
    check_flag_supported,
    check_python_module_available,
    clear_runtime_cache,
    collect_runtime_compatibility,
    get_tool_readiness,
)
from tests.fakes.fake_docker_backend import FakeDockerBackend, FakeResponse


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    data = tmp_path / "data"
    data.mkdir()
    return Settings(
        image="alex88ridolfi/presto5:png",
        data_dir=data.resolve(),
        runs_dir=(tmp_path / "runs").resolve(),
        outputs_dir=(tmp_path / "outputs").resolve(),
        logs_dir=(tmp_path / "logs").resolve(),
        default_cpus=2.0,
        default_memory_mb=1024,
        default_timeout_s=60,
        network="none",
        skip_healthcheck=True,
    )


def test_binary_present(settings: Settings) -> None:
    backend = FakeDockerBackend()
    backend.set_probe_response("which:rfifind", FakeResponse(status=RunStatus.SUCCESS))
    check = check_binary_available(backend, settings, "rfifind")
    assert check.status == "OK"
    assert check.name == "binary.rfifind"
    assert check.kind == "binary"


def test_binary_missing(settings: Settings) -> None:
    backend = FakeDockerBackend()
    backend.set_probe_response(
        "which:stacksearch.py",
        FakeResponse(status=RunStatus.FAILED, exit_code=1),
    )
    check = check_binary_available(backend, settings, "stacksearch.py")
    assert check.status == "ERROR"
    assert "not on PATH" in check.message
    assert check.remediation is not None


def test_python_module_missing(settings: Settings) -> None:
    backend = FakeDockerBackend()
    backend.set_probe_response(
        "module:presto.singlepulse",
        FakeResponse(
            status=RunStatus.FAILED,
            exit_code=1,
            stderr="No module named 'presto.singlepulse'",
        ),
    )
    check = check_python_module_available(backend, settings, "presto.singlepulse")
    assert check.status == "ERROR"
    assert "presto.singlepulse" in check.message
    assert check.kind == "python_module"


def test_python_module_present(settings: Settings) -> None:
    backend = FakeDockerBackend()
    check = check_python_module_available(backend, settings, "presto")
    # default FakeResponse is SUCCESS
    assert check.status == "OK"


def test_python_module_probe_uses_configured_python(settings: Settings) -> None:
    backend = FakeDockerBackend()
    configured = settings.with_overrides(python_bin="python")
    check = check_python_module_available(backend, configured, "presto")
    assert check.status == "OK"

    argv = backend.calls[0].invocation.argv
    image_idx = argv.index(configured.image)
    assert argv[image_idx + 1] == "python"


def test_probe_timeout_is_unknown(settings: Settings) -> None:
    backend = FakeDockerBackend()
    backend.set_probe_response(
        "which:accelsearch", FakeResponse(status=RunStatus.TIMEOUT)
    )
    check = check_binary_available(backend, settings, "accelsearch")
    assert check.status == "UNKNOWN"


def test_backend_error_is_not_fatal(settings: Settings) -> None:
    class _BoomBackend:
        def run(self, invocation: DockerInvocation, timeout_s: int) -> BackendResult:
            raise RuntimeError("docker daemon down")

        def inspect_image_digest(self, image: str) -> str | None:
            return None

    check = check_binary_available(_BoomBackend(), settings, "rfifind")
    assert check.status == "ERROR"  # probe failed -> definitive ERROR, no traceback


def test_rrattrap_ready_false_when_singlepulse_missing(settings: Settings) -> None:
    """rrattrap.py present but presto.singlepulse missing -> blocking ERROR."""
    backend = FakeDockerBackend()
    backend.set_probe_response(
        "which:rrattrap.py", FakeResponse(status=RunStatus.SUCCESS)
    )
    backend.set_probe_response(
        "module:presto.singlepulse",
        FakeResponse(status=RunStatus.FAILED, exit_code=1),
    )
    readiness = get_tool_readiness(backend, settings, "rrattrap")
    assert readiness.tool_name == "rrattrap"
    assert readiness.status == "ERROR"
    assert readiness.blocking is True
    statuses = {c.name: c.status for c in readiness.checks}
    assert statuses["binary.rrattrap.py"] == "OK"
    assert statuses["module.presto.singlepulse"] == "ERROR"


def test_tool_readiness_ok_when_all_present(settings: Settings) -> None:
    backend = FakeDockerBackend()  # all probes default to SUCCESS
    readiness = get_tool_readiness(backend, settings, "accelsearch")
    assert readiness.status == "OK"
    assert readiness.blocking is False


def test_results_are_cached(settings: Settings) -> None:
    clear_runtime_cache()
    backend = FakeDockerBackend()
    check_binary_available(backend, settings, "rfifind")
    check_binary_available(backend, settings, "rfifind")
    assert len(backend.calls) == 1  # second call served from cache


def test_force_refresh_bypasses_cache(settings: Settings) -> None:
    clear_runtime_cache()
    backend = FakeDockerBackend()
    check_binary_available(backend, settings, "rfifind")
    check_binary_available(backend, settings, "rfifind", force_refresh=True)
    assert len(backend.calls) == 2


def test_check_flag_supported() -> None:
    help_text = "Usage: accelsearch [-zmax z] [-numharm h] [-wmax w] [-sigma s]"
    assert check_flag_supported(help_text, "-wmax") is True
    assert check_flag_supported(help_text, "-sigma") is True
    assert check_flag_supported(help_text, "-ncpus") is False
    # token boundary: -zmax must not match inside -zmaxes
    assert check_flag_supported("Usage: [-zmaxes z]", "-zmax") is False
    assert check_flag_supported("", "-wmax") is False


def test_check_binary_help_ok(settings: Settings) -> None:
    backend = FakeDockerBackend()
    backend.set_probe_response(
        "help:accelsearch",
        FakeResponse(
            status=RunStatus.SUCCESS,
            stdout="Usage: accelsearch [-zmax z] [-numharm h] [-wmax w]\n",
        ),
    )
    check, help_text = check_binary_help(backend, settings, "accelsearch")
    assert check.status == "OK"
    assert "-wmax" in help_text


def test_check_binary_help_missing(settings: Settings) -> None:
    backend = FakeDockerBackend()
    backend.set_probe_response(
        "help:nope", FakeResponse(status=RunStatus.FAILED, exit_code=127, stdout="")
    )
    check, help_text = check_binary_help(backend, settings, "nope")
    assert check.status == "ERROR"
    assert help_text == ""


def test_collect_runtime_compatibility_structure(settings: Settings) -> None:
    backend = FakeDockerBackend()
    backend.set_probe_response(
        "module:presto.singlepulse",
        FakeResponse(status=RunStatus.FAILED, exit_code=1),
    )
    compat = collect_runtime_compatibility(backend, settings)
    assert compat.image == settings.image
    # one module failing -> overall not OK
    assert compat.status in {"ERROR", "WARN"}
    names = {r.tool_name for r in compat.tool_readiness}
    assert "rrattrap" in names
    assert "accelsearch" in names
    rrattrap = next(r for r in compat.tool_readiness if r.tool_name == "rrattrap")
    assert rrattrap.blocking is True
