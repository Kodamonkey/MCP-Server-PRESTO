"""Trivial smoke test — confirms the package imports and config builds."""

from __future__ import annotations

from presto_mcp import __version__
from presto_mcp.config import Settings, get_settings


def test_version_string() -> None:
    assert isinstance(__version__, str)
    assert __version__.count(".") == 2


def test_settings_load() -> None:
    s = get_settings()
    assert isinstance(s, Settings)
    assert s.image  # non-empty
    assert s.default_cpus > 0
    assert s.default_memory_mb > 0
    assert s.default_timeout_s > 0
    assert s.network == "none"
