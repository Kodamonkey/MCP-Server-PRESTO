"""Unit test for executor multi-input + input_root + hook plumbing."""

from __future__ import annotations

from pathlib import Path

import pytest

from presto_mcp.config import Settings
from presto_mcp.executor import ExtraInput, RunSpec, execute
from presto_mcp.manifest import load_manifest
from presto_mcp.models import ReadfileMetadata, RunStatus
from tests.fakes.fake_docker_backend import FakeDockerBackend, FakeResponse


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    data = tmp_path / "data"
    data.mkdir()
    (data / "primary.fil").write_bytes(b"\x00" * 8)
    (data / "extra1.mask").write_bytes(b"M")
    (data / "extra2.template").write_bytes(b"T")

    runs = tmp_path / "runs"
    # Pre-seed a prior run for "runs"-root tests.
    prior = runs / "20260517T120000Z-AAAAAA" / "artifacts"
    prior.mkdir(parents=True)
    (prior / "old.fft").write_bytes(b"F")

    return Settings(
        image="alex88ridolfi/presto5:png",
        data_dir=data.resolve(),
        runs_dir=runs.resolve(),
        outputs_dir=(tmp_path / "outputs").resolve(),
        logs_dir=(tmp_path / "logs").resolve(),
        default_cpus=2.0,
        default_memory_mb=1024,
        default_timeout_s=60,
        network="none",
        skip_healthcheck=True,
    )


def _trivial_parser(_stdout: str, _run_dir: Path) -> ReadfileMetadata:
    return ReadfileMetadata(file_format="x", raw_fields={})


def test_extra_inputs_resolved_and_logged(settings: Settings) -> None:
    captured: dict[str, object] = {}

    def builder(ci: str, extras: tuple[str, ...], _rd: Path) -> list[str]:
        captured["container_input"] = ci
        captured["extras"] = extras
        return ["readfile", ci, *extras]

    backend = FakeDockerBackend(
        responses={"readfile": FakeResponse(stdout="ok", status=RunStatus.SUCCESS)}
    )
    spec = RunSpec[ReadfileMetadata](
        tool_name="readfile",
        input_file="primary.fil",
        inputs_extra={},
        container_input_path="",
        presto_argv_builder=builder,
        parser=_trivial_parser,
        timeout_s=60,
        cpus=2.0,
        memory_mb=1024,
        extra_inputs=(
            ExtraInput(path="extra1.mask", root="data"),
            ExtraInput(path="extra2.template", root="data"),
        ),
    )

    result = execute(spec, settings, backend)
    assert result.status == RunStatus.SUCCESS
    assert captured["container_input"] == "/data/primary.fil"
    assert captured["extras"] == ("/data/extra1.mask", "/data/extra2.template")

    m = load_manifest(settings.runs_dir / result.run_id)
    assert m.container_inputs["input_file"] == "/data/primary.fil"
    assert m.container_inputs["extra_input_0"] == "/data/extra1.mask"
    assert m.container_inputs["extra_input_1"] == "/data/extra2.template"


def test_input_file_none_skips_resolution(settings: Settings) -> None:
    backend = FakeDockerBackend(
        responses={"DDplan.py": FakeResponse(stdout="ok", status=RunStatus.SUCCESS)}
    )

    def builder(ci: str, _extras: tuple[str, ...], _rd: Path) -> list[str]:
        assert ci == ""  # primary input absent
        return ["DDplan.py", "-l", "0", "-d", "100"]

    spec = RunSpec[ReadfileMetadata](
        tool_name="ddplan",
        input_file=None,
        inputs_extra={},
        container_input_path="",
        presto_argv_builder=builder,
        parser=_trivial_parser,
        timeout_s=60,
        cpus=2.0,
        memory_mb=1024,
    )
    result = execute(spec, settings, backend)
    assert result.status == RunStatus.SUCCESS
    m = load_manifest(settings.runs_dir / result.run_id)
    assert "input_file" not in m.container_inputs


def test_input_root_runs_mounts_runs_dir(settings: Settings) -> None:
    backend = FakeDockerBackend(
        responses={"realfft": FakeResponse(stdout="ok", status=RunStatus.SUCCESS)}
    )

    def builder(ci: str, _extras: tuple[str, ...], _rd: Path) -> list[str]:
        assert ci == "/runs/20260517T120000Z-AAAAAA/artifacts/old.fft"
        return ["realfft", ci]

    spec = RunSpec[ReadfileMetadata](
        tool_name="realfft",
        input_file="20260517T120000Z-AAAAAA/artifacts/old.fft",
        inputs_extra={},
        container_input_path="",
        presto_argv_builder=builder,
        parser=_trivial_parser,
        timeout_s=60,
        cpus=2.0,
        memory_mb=1024,
        input_root="runs",
    )
    result = execute(spec, settings, backend)
    assert result.status == RunStatus.SUCCESS

    # Check docker_argv includes the /runs read-only mount.
    argv = backend.calls[0].invocation.argv
    runs_mounts = [a for a in argv if a.startswith("type=bind,") and "dst=/runs" in a]
    assert len(runs_mounts) == 1
    assert runs_mounts[0].endswith(",readonly")


def test_pre_invocation_hook_runs_before_docker(settings: Settings, tmp_path: Path) -> None:
    backend = FakeDockerBackend(
        responses={"x": FakeResponse(stdout="ok", status=RunStatus.SUCCESS)}
    )

    captured: dict[str, object] = {}

    def hook(run_dir: Path, extras: tuple[Path, ...]) -> None:
        # Create a marker file in artifacts/ so we can prove the hook ran before docker.
        (run_dir / "artifacts" / "hook.marker").write_text("ok")
        captured["run_dir"] = run_dir
        captured["extras"] = extras

    def builder(ci: str, _extras: tuple[str, ...], rd: Path) -> list[str]:
        assert (rd / "artifacts" / "hook.marker").is_file()
        return ["x", ci]

    spec = RunSpec[ReadfileMetadata](
        tool_name="readfile",
        input_file="primary.fil",
        inputs_extra={},
        container_input_path="",
        presto_argv_builder=builder,
        parser=_trivial_parser,
        timeout_s=60,
        cpus=2.0,
        memory_mb=1024,
        pre_invocation_hook=hook,
    )
    result = execute(spec, settings, backend)
    assert result.status == RunStatus.SUCCESS
    names = {p.name for p in (settings.runs_dir / result.run_id / "artifacts").iterdir()}
    assert "hook.marker" in names
    assert captured["run_dir"] == settings.runs_dir / result.run_id
    assert captured["extras"] == ()
