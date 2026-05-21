"""Shared pytest fixtures + the --run-e2e flag."""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-e2e",
        action="store_true",
        default=False,
        help="Run @pytest.mark.e2e tests (requires Docker + PRESTO image + real data).",
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    if config.getoption("--run-e2e"):
        return
    skipper = pytest.mark.skip(reason="e2e tests skipped (pass --run-e2e to enable)")
    for item in items:
        if "e2e" in item.keywords:
            item.add_marker(skipper)


@pytest.fixture(autouse=True)
def _clear_runtime_cache() -> None:
    """Runtime-capability probes are cached per image; isolate every test."""
    from presto_mcp.runtime_checks import clear_runtime_cache

    clear_runtime_cache()


@pytest.fixture
def stdout_fixture_dir() -> Path:
    """Directory containing real PRESTO stdout captures."""
    return FIXTURES_DIR / "stdout"


@pytest.fixture
def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]
