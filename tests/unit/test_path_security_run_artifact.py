"""Unit tests for path_security.resolve_run_artifact."""

from __future__ import annotations

from pathlib import Path

import pytest

from presto_mcp.errors import PathSecurityError
from presto_mcp.path_security import resolve_run_artifact


@pytest.fixture
def runs_root(tmp_path: Path) -> Path:
    root = tmp_path / "runs"
    run_id = "20260517T120000Z-ABCDEF"
    run = root / run_id
    artifacts = run / "artifacts"
    artifacts.mkdir(parents=True)
    (artifacts / "sample.dat").write_bytes(b"\x00" * 8)
    (artifacts / "sample.inf").write_bytes(b"hdr")
    return root


def test_resolve_valid(runs_root: Path) -> None:
    p = resolve_run_artifact("20260517T120000Z-ABCDEF/artifacts/sample.dat", runs_root)
    assert p.name == "sample.dat"
    assert p.is_file()


def test_resolve_valid_backslash(runs_root: Path) -> None:
    p = resolve_run_artifact("20260517T120000Z-ABCDEF\\artifacts\\sample.dat", runs_root)
    assert p.name == "sample.dat"


def test_reject_empty(runs_root: Path) -> None:
    with pytest.raises(PathSecurityError, match="empty"):
        resolve_run_artifact("", runs_root)


def test_reject_absolute(runs_root: Path) -> None:
    with pytest.raises(PathSecurityError, match="absolute"):
        resolve_run_artifact("/etc/passwd", runs_root)


def test_reject_dotdot(runs_root: Path) -> None:
    with pytest.raises(PathSecurityError, match="forbidden segment"):
        resolve_run_artifact("20260517T120000Z-ABCDEF/artifacts/../../escape", runs_root)


def test_reject_bad_shape(runs_root: Path) -> None:
    with pytest.raises(PathSecurityError, match="expected"):
        resolve_run_artifact("not-a-runid/artifacts/x.dat", runs_root)
    with pytest.raises(PathSecurityError, match="expected"):
        resolve_run_artifact("20260517T120000Z-ABCDEF/bogus/x.dat", runs_root)
    with pytest.raises(PathSecurityError, match="expected"):
        resolve_run_artifact("20260517T120000Z-ABCDEF/artifacts/sub/x.dat", runs_root)


def test_reject_nonexistent(runs_root: Path) -> None:
    with pytest.raises(PathSecurityError, match="does not exist"):
        resolve_run_artifact("20260517T120000Z-ABCDEF/artifacts/ghost.dat", runs_root)


def test_reject_non_string(runs_root: Path) -> None:
    with pytest.raises(PathSecurityError, match="must be a string"):
        resolve_run_artifact(42, runs_root)  # type: ignore[arg-type]
