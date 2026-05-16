"""Unit tests for path_security."""

from __future__ import annotations

from pathlib import Path

import pytest

from presto_mcp.errors import PathSecurityError
from presto_mcp.path_security import (
    create_run_dir,
    ensure_inside_root,
    is_run_id,
    resolve_input_path,
)


@pytest.fixture
def data_root(tmp_path: Path) -> Path:
    root = tmp_path / "data"
    root.mkdir()
    (root / "sample.fil").write_bytes(b"\x00" * 16)
    sub = root / "sub"
    sub.mkdir()
    (sub / "nested.fits").write_bytes(b"\x00" * 16)
    return root


def test_resolve_valid_top_level(data_root: Path) -> None:
    p = resolve_input_path("sample.fil", data_root)
    assert p == (data_root / "sample.fil").resolve()


def test_resolve_valid_nested(data_root: Path) -> None:
    p = resolve_input_path("sub/nested.fits", data_root)
    assert p.name == "nested.fits"


def test_resolve_valid_nested_backslash(data_root: Path) -> None:
    # Windows-style separators in user input must be normalized.
    p = resolve_input_path("sub\\nested.fits", data_root)
    assert p.name == "nested.fits"


def test_reject_empty(data_root: Path) -> None:
    with pytest.raises(PathSecurityError, match="empty"):
        resolve_input_path("", data_root)
    with pytest.raises(PathSecurityError, match="empty"):
        resolve_input_path("   ", data_root)


def test_reject_absolute_posix(data_root: Path) -> None:
    with pytest.raises(PathSecurityError, match="absolute"):
        resolve_input_path("/etc/passwd", data_root)


def test_reject_absolute_windows(data_root: Path) -> None:
    with pytest.raises(PathSecurityError, match="absolute"):
        resolve_input_path("C:\\Windows\\System32\\cmd.exe", data_root)


def test_reject_unc(data_root: Path) -> None:
    with pytest.raises(PathSecurityError, match="absolute"):
        resolve_input_path("\\\\server\\share\\file", data_root)


def test_reject_dotdot(data_root: Path) -> None:
    with pytest.raises(PathSecurityError, match="forbidden segment"):
        resolve_input_path("../escape.txt", data_root)
    with pytest.raises(PathSecurityError, match="forbidden segment"):
        resolve_input_path("sub/../../escape.txt", data_root)


def test_reject_nonexistent(data_root: Path) -> None:
    with pytest.raises(PathSecurityError, match="does not exist"):
        resolve_input_path("ghost.fil", data_root)


def test_reject_directory(data_root: Path) -> None:
    with pytest.raises(PathSecurityError, match="not a regular file"):
        resolve_input_path("sub", data_root)


def test_reject_non_string(data_root: Path) -> None:
    with pytest.raises(PathSecurityError, match="must be a string"):
        resolve_input_path(42, data_root)  # type: ignore[arg-type]


def test_case_mismatch_rejected_when_filesystem_case_sensitive(
    data_root: Path, tmp_path: Path
) -> None:
    """On case-sensitive filesystems we must reject case mismatches.

    On case-insensitive filesystems (Windows NTFS, default macOS) the resolved
    path's casing is what the FS reports for the actual file, so a mis-cased
    input will reveal a different case in ``relative_to`` output and trip the
    check. We construct the test to be valid regardless: a known-good file
    accessed under the wrong case should fail.
    """
    # Skip cleanly if FS is case-insensitive AND it returns the supplied case
    # rather than the canonical case (rare; e.g. some FAT volumes). Practically
    # NTFS and APFS return canonical case so this test always exercises the path.
    canonical = "sample.fil"
    miscased = "Sample.fil"
    canonical_p = (data_root / canonical)
    miscased_p = (data_root / miscased)
    if canonical_p.resolve() == miscased_p.resolve() and canonical_p.exists():
        # case-insensitive: resolve() will report the canonical name; the check
        # compares user-supplied parts to canonical parts and must reject.
        with pytest.raises(PathSecurityError, match="case mismatch"):
            resolve_input_path(miscased, data_root)


def test_ensure_inside_root_ok(tmp_path: Path) -> None:
    root = tmp_path / "r"
    root.mkdir()
    inner = root / "x"
    inner.mkdir()
    ensure_inside_root(inner, root)


def test_ensure_inside_root_rejects(tmp_path: Path) -> None:
    root = tmp_path / "r"
    root.mkdir()
    outside = tmp_path / "other"
    outside.mkdir()
    with pytest.raises(PathSecurityError, match="not inside root"):
        ensure_inside_root(outside, root)


def test_create_run_dir(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    run_id, run_dir = create_run_dir("readfile", runs)
    assert is_run_id(run_id)
    assert run_dir.exists()
    assert (run_dir / "artifacts").is_dir()
    assert (run_dir / "stdout.log").is_file()
    assert (run_dir / "stderr.log").is_file()
    assert run_dir.parent == runs.resolve()


def test_create_run_dir_unique(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    ids = {create_run_dir("readfile", runs)[0] for _ in range(8)}
    assert len(ids) == 8


def test_create_run_dir_bad_tool(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    with pytest.raises(PathSecurityError, match="invalid tool_name"):
        create_run_dir("", runs)
    with pytest.raises(PathSecurityError, match="invalid tool_name"):
        create_run_dir("readfile/x", runs)


def test_is_run_id() -> None:
    assert is_run_id("20260516T143052Z-K7QM3A")
    assert not is_run_id("not-an-id")
    assert not is_run_id("20260516T143052Z-lowercase")
    assert not is_run_id("20260516T143052Z-K7QM3")  # too short
