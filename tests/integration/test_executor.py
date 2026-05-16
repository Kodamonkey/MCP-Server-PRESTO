"""Executor integration tests against ``FakeDockerBackend``."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from presto_mcp.config import Settings
from presto_mcp.executor import RunSpec, execute
from presto_mcp.manifest import load_manifest
from presto_mcp.models import ReadfileMetadata, RunStatus
from tests.fakes.fake_docker_backend import FakeDockerBackend, FakeResponse


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    data = tmp_path / "data"
    data.mkdir()
    (data / "sample.fil").write_bytes(b"\x00" * 16)
    runs = tmp_path / "runs"
    runs.mkdir()
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    logs = tmp_path / "logs"
    logs.mkdir()
    return Settings(
        image="alex88ridolfi/presto5:png",
        data_dir=data.resolve(),
        runs_dir=runs.resolve(),
        outputs_dir=outputs.resolve(),
        logs_dir=logs.resolve(),
        default_cpus=2.0,
        default_memory_mb=1024,
        default_timeout_s=60,
        network="none",
        skip_healthcheck=True,
    )


def _readfile_argv(container_input: str, _run_dir: Path) -> list[str]:
    return ["readfile", container_input]


def _readfile_parser(stdout: str, _run_dir: Path) -> ReadfileMetadata:
    return ReadfileMetadata(file_format="SIGPROC", raw_fields={"_": stdout[:32]})


def test_execute_success_writes_manifest_and_logs(settings: Settings) -> None:
    backend = FakeDockerBackend(
        responses={
            "readfile": FakeResponse(
                stdout="hello readfile\n",
                stderr="",
                exit_code=0,
                status=RunStatus.SUCCESS,
            )
        }
    )
    spec = RunSpec[ReadfileMetadata](
        tool_name="readfile",
        input_file="sample.fil",
        inputs_extra={},
        container_input_path="/data/sample.fil",
        presto_argv_builder=_readfile_argv,
        parser=_readfile_parser,
        timeout_s=60,
        cpus=2.0,
        memory_mb=1024,
    )

    result = execute(spec, settings, backend)

    assert result.status == RunStatus.SUCCESS
    assert result.result is not None
    assert result.manifest_uri == f"presto://runs/{result.run_id}/manifest"
    assert result.stdout_uri == f"presto://runs/{result.run_id}/stdout"

    run_dir = settings.runs_dir / result.run_id
    assert (run_dir / "stdout.log").read_text(encoding="utf-8") == "hello readfile\n"
    m = load_manifest(run_dir)
    assert m.tool == "readfile"
    assert m.status == RunStatus.SUCCESS
    assert m.exit_code == 0
    assert m.docker_argv[0] == "docker"
    assert m.presto_argv == ["readfile", "/data/sample.fil"]
    assert m.inputs["input_file"].endswith("sample.fil")
    assert m.container_inputs["input_file"] == "/data/sample.fil"

    # Backend was called exactly once with timeout passed through.
    assert len(backend.calls) == 1
    assert backend.calls[0].timeout_s == 60


def test_execute_failed_still_writes_manifest(settings: Settings) -> None:
    backend = FakeDockerBackend(
        responses={
            "readfile": FakeResponse(
                stdout="",
                stderr="readfile: cannot open\n",
                exit_code=1,
                status=RunStatus.FAILED,
                error="exit 1",
            )
        }
    )
    spec = RunSpec[ReadfileMetadata](
        tool_name="readfile",
        input_file="sample.fil",
        inputs_extra={},
        container_input_path="/data/sample.fil",
        presto_argv_builder=_readfile_argv,
        parser=_readfile_parser,
        timeout_s=60,
        cpus=2.0,
        memory_mb=1024,
    )

    result = execute(spec, settings, backend)

    assert result.status == RunStatus.FAILED
    assert result.result is None  # never parse on failure

    m = load_manifest(settings.runs_dir / result.run_id)
    assert m.status == RunStatus.FAILED
    assert m.exit_code == 1
    assert m.error == "exit 1"


def test_execute_timeout_records_status(settings: Settings) -> None:
    backend = FakeDockerBackend(
        responses={
            "readfile": FakeResponse(
                stdout="",
                stderr="killed\n",
                exit_code=None,  # type: ignore[arg-type]
                status=RunStatus.TIMEOUT,
                error="timed out after 60s",
            )
        }
    )
    spec = RunSpec[ReadfileMetadata](
        tool_name="readfile",
        input_file="sample.fil",
        inputs_extra={},
        container_input_path="/data/sample.fil",
        presto_argv_builder=_readfile_argv,
        parser=_readfile_parser,
        timeout_s=60,
        cpus=2.0,
        memory_mb=1024,
    )

    result = execute(spec, settings, backend)

    assert result.status == RunStatus.TIMEOUT
    m = load_manifest(settings.runs_dir / result.run_id)
    assert m.status == RunStatus.TIMEOUT
    assert m.error == "timed out after 60s"


def test_execute_parser_failure_marks_failed(settings: Settings) -> None:
    def bad_parser(_stdout: str, _run_dir: Path) -> ReadfileMetadata:
        raise ValueError("synthetic")

    backend = FakeDockerBackend(
        responses={"readfile": FakeResponse(stdout="ok", status=RunStatus.SUCCESS)}
    )
    spec = RunSpec[ReadfileMetadata](
        tool_name="readfile",
        input_file="sample.fil",
        inputs_extra={},
        container_input_path="/data/sample.fil",
        presto_argv_builder=_readfile_argv,
        parser=bad_parser,
        timeout_s=60,
        cpus=2.0,
        memory_mb=1024,
    )

    result = execute(spec, settings, backend)

    assert result.status == RunStatus.FAILED
    assert "parser failed" in (result.error or "")
    m = load_manifest(settings.runs_dir / result.run_id)
    assert m.status == RunStatus.FAILED
    assert m.exit_code == 0  # backend succeeded; parser killed it


def test_execute_collects_artifacts(settings: Settings) -> None:
    backend = FakeDockerBackend(
        responses={
            "readfile": FakeResponse(
                stdout="ok",
                status=RunStatus.SUCCESS,
                artifacts={"out.mask": b"M", "out.stats": b"S"},
            )
        }
    )
    spec = RunSpec[ReadfileMetadata](
        tool_name="readfile",
        input_file="sample.fil",
        inputs_extra={},
        container_input_path="/data/sample.fil",
        presto_argv_builder=_readfile_argv,
        parser=_readfile_parser,
        timeout_s=60,
        cpus=2.0,
        memory_mb=1024,
    )

    result = execute(spec, settings, backend)
    assert sorted(result.artifact_uris) == [
        f"presto://runs/{result.run_id}/artifacts/out.mask",
        f"presto://runs/{result.run_id}/artifacts/out.stats",
    ]
    m = load_manifest(settings.runs_dir / result.run_id)
    assert sorted(m.artifacts) == ["out.mask", "out.stats"]


def test_execute_background_returns_running_then_completes(settings: Settings) -> None:
    backend = FakeDockerBackend(
        responses={
            "readfile": FakeResponse(
                stdout="hello readfile\n",
                status=RunStatus.SUCCESS,
            )
        }
    )
    spec = RunSpec[ReadfileMetadata](
        tool_name="readfile",
        input_file="sample.fil",
        inputs_extra={},
        container_input_path="/data/sample.fil",
        presto_argv_builder=_readfile_argv,
        parser=_readfile_parser,
        timeout_s=60,
        cpus=2.0,
        memory_mb=1024,
    )

    result = execute(spec, settings, backend, background=True)

    assert result.status == RunStatus.RUNNING
    assert result.result is None

    run_dir = settings.runs_dir / result.run_id
    deadline = time.monotonic() + 5.0
    final = load_manifest(run_dir)
    while final.status == RunStatus.RUNNING and time.monotonic() < deadline:
        time.sleep(0.05)
        final = load_manifest(run_dir)

    assert final.status == RunStatus.SUCCESS
    assert final.exit_code == 0
    assert (run_dir / "stdout.log").read_text(encoding="utf-8") == "hello readfile\n"
