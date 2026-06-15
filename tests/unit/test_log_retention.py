"""Unit tests for server-log retention (prune_server_logs)."""

from __future__ import annotations

import os
import time
from pathlib import Path

from presto_mcp.observability.structured_logger import prune_server_logs


def _touch_session(server_dir: Path, sid: str, *, age: float) -> list[Path]:
    paths = [server_dir / f"server-{sid}.log", server_dir / f"server-{sid}.jsonl"]
    for p in paths:
        p.write_text("x", encoding="utf-8")
        os.utime(p, (age, age))
    return paths


def test_prune_keeps_newest_n_and_latest(tmp_path: Path) -> None:
    server = tmp_path / "server"
    server.mkdir()
    base = time.time()
    # 5 sessions, increasing mtime → last is newest. Nonces are valid base32
    # (A-Z, 2-7); the timestamp distinguishes them.
    sids = [
        "20260531T000002Z-AAAAAA",
        "20260531T000003Z-AAAAAB",
        "20260531T000004Z-AAAAAC",
        "20260531T000005Z-AAAAAD",
        "20260531T000006Z-AAAAAE",
    ]
    for i, sid in enumerate(sids, start=1):
        _touch_session(server, sid, age=base + i)
    (server / "latest.log").write_text("L", encoding="utf-8")
    (server / "latest.jsonl").write_text("L", encoding="utf-8")

    deleted = prune_server_logs(tmp_path, keep=2)

    assert deleted == 6  # 3 oldest sessions × 2 files
    remaining = sorted(p.name for p in server.iterdir())
    # newest 2 sessions kept + latest.* untouched
    assert "server-20260531T000006Z-AAAAAE.log" in remaining
    assert "server-20260531T000005Z-AAAAAD.log" in remaining
    assert "server-20260531T000002Z-AAAAAA.log" not in remaining
    assert "latest.log" in remaining
    assert "latest.jsonl" in remaining


def test_prune_preserves_current_session(tmp_path: Path) -> None:
    server = tmp_path / "server"
    server.mkdir()
    base = time.time()
    _touch_session(server, "20260531T000001Z-OLDEST", age=base + 1)  # oldest
    _touch_session(server, "20260531T000009Z-NEWEST", age=base + 9)

    # keep=1 would drop OLDEST, but mark it current → must survive.
    prune_server_logs(tmp_path, keep=1, current_session_id="20260531T000001Z-OLDEST")

    names = {p.name for p in server.iterdir()}
    assert "server-20260531T000001Z-OLDEST.log" in names
    assert "server-20260531T000009Z-NEWEST.log" in names


def test_prune_missing_dir_is_safe(tmp_path: Path) -> None:
    assert prune_server_logs(tmp_path / "nope", keep=5) == 0
