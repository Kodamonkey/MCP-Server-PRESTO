"""Static tool-metadata registry: category, artifact contract, profile membership.

Pure data + pure functions. No I/O, no FastMCP, no Docker, no PRESTO execution.

Two consumers:
  * ``server_tools.register_tools`` filters the exposed MCP catalog by the active
    ``PRESTO_TOOL_PROFILE`` (see :data:`PROFILES` / :func:`resolve_profile`).
  * The ``requires`` / ``produces`` artifact contract is a machine-readable
    dependency map for future routing (it is data only — nothing executes it).

Keys are **short** tool names (no ``presto.`` prefix). The registered MCP tool
name is ``presto.<short>``.
"""

from __future__ import annotations

from dataclasses import dataclass

# Artifact-kind vocabulary used by `requires` / `produces`. Coarse on purpose —
# it expresses the dependency *shape*, not a precise file type.
#   none      no prior artifact needed
#   raw       a raw filterbank / PSRFITS file under DATA_DIR
#   run_id    an existing run id (reflection / bundling)
#   mask/stats/weights/zaplist/birds/ignorechan   RFI products
#   ddplan/dat/fft/accel/candidates               search-pipeline products
#   pfd/profile/toa/groups/singlepulse/spd        fold / single-pulse products
#   par/metadata/summary/listing/manifest/report/plot   inspection / review


@dataclass(frozen=True)
class ToolMeta:
    """Routing metadata for one MCP tool."""

    category: str
    requires: tuple[str, ...] = ()
    produces: tuple[str, ...] = ()
    # Hint for a future finer-grained default than the coarse profile filter.
    # Experimental / advanced / rarely-first tools are flagged not-visible.
    default_visible: bool = True


# --- per-tool metadata (short name -> ToolMeta) --------------------------------

TOOL_METADATA: dict[str, ToolMeta] = {
    # triage / reflection
    "validate_environment": ToolMeta("triage", ("none",), ("report",)),
    "list_data_files": ToolMeta("triage", ("none",), ("listing",)),
    "readfile": ToolMeta("inspection", ("raw",), ("metadata",)),
    "list_runs": ToolMeta("triage", ("none",), ("listing",)),
    "get_run_manifest": ToolMeta("triage", ("run_id",), ("manifest",)),
    "summarize_run": ToolMeta("triage", ("run_id",), ("summary",)),
    "inspect_artifacts": ToolMeta("triage", ("run_id",), ("listing",)),
    # data preparation
    "psrfits2fil": ToolMeta("data_prep", ("raw",), ("raw",)),
    "downsample_filterbank": ToolMeta("data_prep", ("raw",), ("raw",)),
    "fb_truncate": ToolMeta("data_prep", ("raw",), ("raw",)),
    # RFI mitigation
    "rfifind": ToolMeta("rfi", ("raw",), ("mask", "stats")),
    "rfifind_stats": ToolMeta("rfi", ("stats",), ("summary",)),
    "weights_to_ignorechan": ToolMeta(
        "rfi", ("weights",), ("ignorechan",), default_visible=False
    ),
    "makezaplist": ToolMeta(
        "rfi", ("birds",), ("zaplist",), default_visible=False
    ),
    "zapbirds": ToolMeta("rfi", ("fft", "zaplist"), ("fft",)),
    "simple_zapbirds": ToolMeta(
        "rfi", ("fft", "birds"), ("fft",), default_visible=False
    ),
    # dedispersion
    "ddplan": ToolMeta("dedispersion", ("none",), ("ddplan",)),
    "prepdata": ToolMeta("dedispersion", ("raw",), ("dat",)),
    "prepsubband": ToolMeta("dedispersion", ("raw",), ("dat",)),
    # periodic / Fourier search
    "realfft": ToolMeta("periodic_search", ("dat",), ("fft",)),
    "accelsearch": ToolMeta("periodic_search", ("fft",), ("accel",)),
    "sifting": ToolMeta("periodic_search", ("accel",), ("candidates",)),
    "prepfold": ToolMeta("periodic_search", ("raw",), ("pfd",)),
    "stacksearch": ToolMeta(
        "periodic_search", ("fft",), ("candidates",), default_visible=False
    ),
    "search_bin": ToolMeta(
        "periodic_search", ("fft",), ("candidates",), default_visible=False
    ),
    # single-pulse / transients
    "single_pulse_search": ToolMeta("single_pulse", ("dat",), ("singlepulse",)),
    "rrattrap": ToolMeta(
        "single_pulse", ("singlepulse",), ("groups",), default_visible=False
    ),
    "make_spd": ToolMeta(
        "single_pulse", ("raw", "groups", "singlepulse"), ("spd",)
    ),
    "plot_spd": ToolMeta("single_pulse", ("spd",), ("plot",)),
    "single_pulse_diagnostic": ToolMeta(
        "single_pulse", ("dat", "inf", "raw"), ("spd", "plot")
    ),
    "waterfaller": ToolMeta("single_pulse", ("raw",), ("plot",)),
    # folding QC
    "pfd2png": ToolMeta("fold_qc", ("pfd",), ("plot",), default_visible=False),
    "sum_profiles": ToolMeta(
        "fold_qc", ("profile",), ("profile", "plot"), default_visible=False
    ),
    "fourier_fold": ToolMeta(
        "fold_qc", ("fft",), ("profile", "plot"), default_visible=False
    ),
    "pfdzap": ToolMeta("fold_qc", ("pfd",), ("pfd",), default_visible=False),
    # timing
    "get_toas": ToolMeta("timing", ("pfd",), ("toa",)),
    # review / QC (utility, no Docker)
    "compare_periods": ToolMeta("review", ("par",), ("matches",)),
    "binary_info": ToolMeta("review", ("par",), ("summary",)),
    "compile_candidate_report_pdf": ToolMeta("review", ("run_id",), ("report",)),
    # modern reporting / artifact layer (post-hoc, reads a workdir)
    "export_candidates_csv": ToolMeta("reporting", ("run_id",), ("report",)),
    "generate_summary_json": ToolMeta("reporting", ("run_id",), ("summary",)),
    "generate_visual_artifacts": ToolMeta("reporting", ("run_id",), ("plot",)),
    "generate_candidate_waterfalls": ToolMeta("reporting", ("run_id", "raw"), ("plot",)),
    "generate_report_html": ToolMeta("reporting", ("run_id",), ("report",)),
    "generate_report_markdown": ToolMeta("reporting", ("run_id",), ("report",)),
    "generate_modern_report_bundle": ToolMeta("reporting", ("run_id", "raw"), ("report",)),
}


# --- profiles ------------------------------------------------------------------

# Core tools are present in every profile: triage, reflection and single-file
# inspection. They are also what `background` polling depends on
# (`get_run_manifest`), so no non-core profile can lose the ability to poll.
_CORE: frozenset[str] = frozenset(
    {
        "validate_environment",
        "list_data_files",
        "readfile",
        "list_runs",
        "get_run_manifest",
        "summarize_run",
        "inspect_artifacts",
    }
)

PROFILES: dict[str, frozenset[str]] = {
    "core": _CORE,
    "rfi_prep": _CORE
    | {
        "psrfits2fil",
        "downsample_filterbank",
        "fb_truncate",
        "rfifind",
        "rfifind_stats",
        "weights_to_ignorechan",
        "makezaplist",
    },
    "periodic": _CORE
    | {
        "rfifind",
        "ddplan",
        "prepsubband",
        "prepdata",
        "realfft",
        "zapbirds",
        "accelsearch",
        "sifting",
        "prepfold",
        "get_toas",
    },
    "single_pulse": _CORE
    | {
        "rfifind",
        "ddplan",
        "prepsubband",
        "prepdata",
        "single_pulse_search",
        "rrattrap",
        "make_spd",
        "plot_spd",
        "single_pulse_diagnostic",
        "waterfaller",
    },
    "review_qc": _CORE
    | {
        "compare_periods",
        "binary_info",
        "pfd2png",
        "waterfaller",
        "compile_candidate_report_pdf",
        "export_candidates_csv",
        "generate_summary_json",
        "generate_visual_artifacts",
        "generate_candidate_waterfalls",
        "generate_report_html",
        "generate_report_markdown",
        "generate_modern_report_bundle",
    },
    "advanced": _CORE
    | {
        "search_bin",
        "stacksearch",
        "simple_zapbirds",
        "sum_profiles",
        "pfdzap",
        "fourier_fold",
    },
    "all": frozenset(TOOL_METADATA),
}

PROFILE_NAMES: tuple[str, ...] = tuple(PROFILES)

DEFAULT_PROFILE = "all"


def _validate() -> None:
    """Fail fast at import if a profile names a tool with no metadata entry."""
    for profile, tools in PROFILES.items():
        unknown = tools - set(TOOL_METADATA)
        if unknown:
            raise ValueError(
                f"profile {profile!r} references unknown tools: {sorted(unknown)}"
            )


_validate()


def resolve_profile(name: str | None) -> frozenset[str]:
    """Return the short-name set for ``name``.

    An empty or unrecognised profile resolves to ``all`` (fail-open: never hide
    tools because of a typo). Callers that want to warn on an unknown name
    should check it against :data:`PROFILE_NAMES` first.
    """
    if not name:
        return PROFILES[DEFAULT_PROFILE]
    return PROFILES.get(name.strip().lower(), PROFILES[DEFAULT_PROFILE])


def tool_meta(short_name: str) -> ToolMeta | None:
    """Return the :class:`ToolMeta` for a short tool name, or ``None``."""
    return TOOL_METADATA.get(short_name)


__all__ = [
    "DEFAULT_PROFILE",
    "PROFILES",
    "PROFILE_NAMES",
    "TOOL_METADATA",
    "ToolMeta",
    "resolve_profile",
    "tool_meta",
]
