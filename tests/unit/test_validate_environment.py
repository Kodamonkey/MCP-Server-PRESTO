"""Tests for the presto.validate_environment utility tool."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from presto_mcp.config import Settings
from presto_mcp.tools import validate_environment as ve


def _settings(tmp_path: Path, *, data_dir: Path | None = None) -> Settings:
    return Settings(
        image="alex88ridolfi/presto5:png",
        data_dir=data_dir if data_dir is not None else tmp_path / "data",
        runs_dir=tmp_path / "runs",
        outputs_dir=tmp_path / "outputs",
        default_cpus=4.0,
        default_memory_mb=8192,
        default_timeout_s=1800,
        network="none",
        skip_healthcheck=True,
    )


def _fake_docker_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ve.shutil, "which", lambda _: "/usr/bin/docker")


def _fake_docker_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ve.shutil, "which", lambda _: None)


def _mock_run_factory(
    version_rc: int = 0,
    daemon_rc: int = 0,
    image_rc: int = 0,
    version_stdout: bytes = b"Docker 27\n",
):
    def _mock_run(argv, **kwargs):  # type: ignore[no-untyped-def]
        if argv[:2] == ["/usr/bin/docker", "--version"] or argv[1:2] == ["--version"]:
            return subprocess.CompletedProcess(
                argv, version_rc, stdout=version_stdout, stderr=b""
            )
        if argv[:2] == ["/usr/bin/docker", "info"] or argv[1:2] == ["info"]:
            return subprocess.CompletedProcess(
                argv, daemon_rc, stdout=b"server ok\n", stderr=b"daemon unavailable\n"
            )
        if "image" in argv and "inspect" in argv:
            return subprocess.CompletedProcess(argv, image_rc, stdout=b"[{}]", stderr=b"")
        return subprocess.CompletedProcess(argv, 0, stdout=b"", stderr=b"")

    return _mock_run


def test_ok_when_docker_and_image_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = tmp_path / "data"
    data.mkdir()
    (data / "obs.fil").write_bytes(b"x" * 16)
    _fake_docker_present(monkeypatch)
    monkeypatch.setattr(ve.subprocess, "run", _mock_run_factory())

    res = ve.run_validate_environment(settings=_settings(tmp_path, data_dir=data))
    assert res.status == "OK"
    names = {c.name for c in res.checks}
    assert {
        "settings.load",
        "data_dir.exists",
        "docker.cli",
        "docker.version",
        "docker.daemon",
        "docker.image",
    } <= names


def test_warn_when_data_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data = tmp_path / "data"
    data.mkdir()
    _fake_docker_present(monkeypatch)
    monkeypatch.setattr(ve.subprocess, "run", _mock_run_factory())

    res = ve.run_validate_environment(settings=_settings(tmp_path, data_dir=data))
    assert res.status == "WARN"
    assert any(c.name == "data_dir.has_files" and c.status == "WARN" for c in res.checks)


def test_error_when_docker_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = tmp_path / "data"
    data.mkdir()
    (data / "obs.fil").write_bytes(b"x" * 16)
    _fake_docker_absent(monkeypatch)

    res = ve.run_validate_environment(
        check_image=False, settings=_settings(tmp_path, data_dir=data)
    )
    assert res.status == "ERROR"
    assert any(c.name == "docker.cli" and c.status == "ERROR" for c in res.checks)


def test_warn_when_image_absent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data = tmp_path / "data"
    data.mkdir()
    (data / "obs.fil").write_bytes(b"x" * 16)
    _fake_docker_present(monkeypatch)
    monkeypatch.setattr(ve.subprocess, "run", _mock_run_factory(image_rc=1))

    res = ve.run_validate_environment(settings=_settings(tmp_path, data_dir=data))
    assert res.status == "WARN"
    assert any(c.name == "docker.image" and c.status == "WARN" for c in res.checks)


def test_error_when_docker_daemon_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = tmp_path / "data"
    data.mkdir()
    (data / "obs.fil").write_bytes(b"x" * 16)
    _fake_docker_present(monkeypatch)
    monkeypatch.setattr(ve.subprocess, "run", _mock_run_factory(daemon_rc=1))

    res = ve.run_validate_environment(settings=_settings(tmp_path, data_dir=data))
    assert res.status == "ERROR"
    assert any(c.name == "docker.daemon" and c.status == "ERROR" for c in res.checks)
    assert not any(c.name == "docker.image" for c in res.checks)


def test_zero_byte_placeholder_detected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = tmp_path / "data"
    data.mkdir()
    (data / "real.fil").write_bytes(b"x" * 8)
    (data / "placeholder.fil").write_bytes(b"")
    _fake_docker_present(monkeypatch)
    monkeypatch.setattr(ve.subprocess, "run", _mock_run_factory())

    res = ve.run_validate_environment(settings=_settings(tmp_path, data_dir=data))
    assert any(
        c.name == "data_dir.zero_byte_files" and c.status == "WARN" for c in res.checks
    )


def test_never_raises_on_docker_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = tmp_path / "data"
    data.mkdir()
    (data / "obs.fil").write_bytes(b"x" * 8)
    _fake_docker_present(monkeypatch)

    def _boom(*_a, **_k):  # type: ignore[no-untyped-def]
        raise subprocess.TimeoutExpired(cmd="docker", timeout=5)

    monkeypatch.setattr(ve.subprocess, "run", _boom)
    res = ve.run_validate_environment(settings=_settings(tmp_path, data_dir=data))
    assert res.status == "ERROR"
    assert any(c.name == "docker.version" and c.status == "ERROR" for c in res.checks)
