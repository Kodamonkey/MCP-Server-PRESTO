"""Unit tests for presto_mcp.tool_metadata (registry + profile resolution)."""

from __future__ import annotations

from presto_mcp.tool_metadata import (
    PROFILE_NAMES,
    PROFILES,
    TOOL_METADATA,
    resolve_profile,
    tool_meta,
)


def test_every_profile_references_known_tools() -> None:
    for profile, tools in PROFILES.items():
        unknown = tools - set(TOOL_METADATA)
        assert not unknown, f"profile {profile} names unknown tools: {unknown}"


def test_core_is_subset_of_every_profile() -> None:
    core = PROFILES["core"]
    for profile, tools in PROFILES.items():
        assert core <= tools, f"profile {profile} is missing core tools"


def test_all_profile_covers_full_registry() -> None:
    assert PROFILES["all"] == frozenset(TOOL_METADATA)


def test_get_run_manifest_in_every_profile() -> None:
    # background polling depends on it — no profile may drop it.
    for tools in PROFILES.values():
        assert "get_run_manifest" in tools


def test_resolve_profile_known() -> None:
    assert resolve_profile("core") == PROFILES["core"]
    assert resolve_profile("  Core ") == PROFILES["core"]  # trimmed + lowercased


def test_resolve_profile_unknown_falls_back_to_all() -> None:
    assert resolve_profile("bogus") == PROFILES["all"]
    assert resolve_profile(None) == PROFILES["all"]
    assert resolve_profile("") == PROFILES["all"]


def test_profile_names_match_profiles() -> None:
    assert set(PROFILE_NAMES) == set(PROFILES)


def test_phantom_tools_now_have_metadata() -> None:
    # pfdzap / fourier_fold are registered tools; they must carry metadata.
    for name in ("pfdzap", "fourier_fold"):
        meta = tool_meta(name)
        assert meta is not None
        assert meta.category == "fold_qc"
        assert meta.default_visible is False


def test_utility_review_tools_default_visible() -> None:
    for name in ("compare_periods", "binary_info"):
        meta = tool_meta(name)
        assert meta is not None
        assert meta.category == "review"
