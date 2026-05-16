"""Argv builder is security-critical. Pin its output verbatim."""

from __future__ import annotations

from pathlib import Path

import pytest

from presto_mcp.docker_backend import (
    CONTAINER_DATA_MOUNT,
    CONTAINER_OUTPUT_MOUNT,
    build_invocation,
)
from presto_mcp.errors import DockerInvocationError


@pytest.fixture
def dirs(tmp_path: Path) -> tuple[Path, Path]:
    data = tmp_path / "data"
    data.mkdir()
    run = tmp_path / "runs" / "20260516T143052Z-K7QM3A"
    run.mkdir(parents=True)
    return data, run


def test_golden_argv_readfile(dirs: tuple[Path, Path]) -> None:
    data, run = dirs
    inv = build_invocation(
        image="alex88ridolfi/presto5:png",
        presto_argv=["readfile", "/data/sample.fil"],
        data_dir=data,
        run_dir=run,
        cpus=4.0,
        memory_mb=8192,
        container_name="presto-20260516T143052Z-K7QM3A",
    )
    assert inv.argv == [
        "docker", "run", "--rm",
        "--name", "presto-20260516T143052Z-K7QM3A",
        "--network=none",
        "--cpus=4.0",
        "--memory=8192m",
        "--pids-limit=256",
        "--security-opt", "no-new-privileges",
        "--stop-timeout=5",
        "--mount", f"type=bind,src={data.resolve()},dst={CONTAINER_DATA_MOUNT},readonly",
        "--mount", f"type=bind,src={run.resolve()},dst={CONTAINER_OUTPUT_MOUNT}",
        "alex88ridolfi/presto5:png",
        "readfile", "/data/sample.fil",
    ]


def test_argv_contains_network_none(dirs: tuple[Path, Path]) -> None:
    data, run = dirs
    inv = build_invocation(
        image="i:t", presto_argv=["x"], data_dir=data, run_dir=run,
        cpus=1.0, memory_mb=512, container_name="c",
    )
    assert "--network=none" in inv.argv


def test_argv_data_readonly_run_rw(dirs: tuple[Path, Path]) -> None:
    data, run = dirs
    inv = build_invocation(
        image="i:t", presto_argv=["x"], data_dir=data, run_dir=run,
        cpus=1.0, memory_mb=512, container_name="c",
    )
    mounts = [a for a in inv.argv if a.startswith("type=bind")]
    assert len(mounts) == 2
    data_mount = next(m for m in mounts if ",dst=/data," in m)
    out_mount = next(m for m in mounts if m.endswith(",dst=/outputs"))
    assert data_mount.endswith(",readonly"), data_mount
    # Suffix check only — the temp dir path itself can contain the word "readonly".
    assert not out_mount.endswith(",readonly"), out_mount


def test_argv_pids_no_new_privileges(dirs: tuple[Path, Path]) -> None:
    data, run = dirs
    inv = build_invocation(
        image="i:t", presto_argv=["x"], data_dir=data, run_dir=run,
        cpus=1.0, memory_mb=512, container_name="c",
    )
    assert "--pids-limit=256" in inv.argv
    assert "no-new-privileges" in inv.argv


def test_argv_no_shell_metachars(dirs: tuple[Path, Path]) -> None:
    """No element should be a shell pipeline / metachar string."""
    data, run = dirs
    inv = build_invocation(
        image="i:t", presto_argv=["readfile", "/data/x.fil"], data_dir=data, run_dir=run,
        cpus=1.0, memory_mb=512, container_name="c",
    )
    for el in inv.argv:
        assert "&&" not in el
        assert ";" not in el
        assert "|" not in el
        assert el != "sh"
        assert el != "bash"


def test_reject_empty_image(dirs: tuple[Path, Path]) -> None:
    data, run = dirs
    with pytest.raises(DockerInvocationError, match="image"):
        build_invocation(
            image="", presto_argv=["x"], data_dir=data, run_dir=run,
            cpus=1, memory_mb=512, container_name="c",
        )


def test_reject_empty_argv(dirs: tuple[Path, Path]) -> None:
    data, run = dirs
    with pytest.raises(DockerInvocationError, match="presto_argv"):
        build_invocation(
            image="i:t", presto_argv=[], data_dir=data, run_dir=run,
            cpus=1, memory_mb=512, container_name="c",
        )


def test_reject_bad_container_name(dirs: tuple[Path, Path]) -> None:
    data, run = dirs
    with pytest.raises(DockerInvocationError, match="container_name"):
        build_invocation(
            image="i:t", presto_argv=["x"], data_dir=data, run_dir=run,
            cpus=1, memory_mb=512, container_name="bad name",
        )


def test_argv_image_precedes_command(dirs: tuple[Path, Path]) -> None:
    data, run = dirs
    inv = build_invocation(
        image="img:tag", presto_argv=["readfile", "/data/x.fil"],
        data_dir=data, run_dir=run,
        cpus=1.0, memory_mb=512, container_name="c",
    )
    image_idx = inv.argv.index("img:tag")
    cmd_idx = inv.argv.index("readfile")
    assert image_idx < cmd_idx
