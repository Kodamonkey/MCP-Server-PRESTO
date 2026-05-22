"""Tests for the presto.list_data_files utility tool."""

from __future__ import annotations

from pathlib import Path

import pytest

from presto_mcp.config import Settings
from presto_mcp.tools.list_data_files import run_list_data_files


def _settings(tmp_path: Path, data_dir: Path) -> Settings:
    return Settings(
        image="alex88ridolfi/presto5:png",
        data_dir=data_dir,
        runs_dir=tmp_path / "runs",
        outputs_dir=tmp_path / "outputs",
        default_cpus=2.0,
        default_memory_mb=1024,
        default_timeout_s=60,
        network="none",
        skip_healthcheck=True,
    )


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    d = tmp_path / "data"
    d.mkdir()
    (d / "obs1.fil").write_bytes(b"a" * 10)
    (d / "obs2.fits").write_bytes(b"a" * 20)
    (d / "notes.txt").write_text("ok", encoding="utf-8")
    (d / "blob.bin").write_bytes(b"b" * 5)
    (d / ".secret").write_text("nope", encoding="utf-8")
    sub = d / "sub"
    sub.mkdir()
    (sub / "nested.fil").write_bytes(b"n" * 3)
    return d


def test_lists_and_classifies(tmp_path: Path, data_dir: Path) -> None:
    res = run_list_data_files(settings=_settings(tmp_path, data_dir))
    names = {f.relative_path for f in res.files}
    assert "obs1.fil" in names
    assert "obs2.fits" in names
    assert "notes.txt" in names
    assert "blob.bin" in names
    assert "sub/nested.fil" in names
    # Hidden excluded by default.
    assert ".secret" not in names
    # Classification.
    by_path = {f.relative_path: f.likely_type for f in res.files}
    assert by_path["obs1.fil"] == "filterbank"
    assert by_path["obs2.fits"] == "fits"
    assert by_path["notes.txt"] == "text"
    assert by_path["blob.bin"] == "unknown"


def test_include_hidden(tmp_path: Path, data_dir: Path) -> None:
    res = run_list_data_files(
        include_hidden=True, settings=_settings(tmp_path, data_dir)
    )
    names = {f.relative_path for f in res.files}
    assert ".secret" in names


def test_limit_respected(tmp_path: Path, data_dir: Path) -> None:
    res = run_list_data_files(limit=2, settings=_settings(tmp_path, data_dir))
    assert res.count == 2
    assert len(res.files) == 2


def test_extension_filter(tmp_path: Path, data_dir: Path) -> None:
    res = run_list_data_files(
        extensions=[".fil"], settings=_settings(tmp_path, data_dir)
    )
    assert {f.extension for f in res.files} == {".fil"}
    # Bare extensions normalized.
    res2 = run_list_data_files(
        extensions=["fits"], settings=_settings(tmp_path, data_dir)
    )
    assert {f.extension for f in res2.files} == {".fits"}


def test_no_absolute_paths_leak(tmp_path: Path, data_dir: Path) -> None:
    res = run_list_data_files(settings=_settings(tmp_path, data_dir))
    for f in res.files:
        assert not Path(f.relative_path).is_absolute()
        assert str(data_dir) not in f.relative_path


def test_missing_data_dir_returns_empty(tmp_path: Path) -> None:
    res = run_list_data_files(
        settings=_settings(tmp_path, tmp_path / "does_not_exist")
    )
    assert res.count == 0
    assert res.files == []
