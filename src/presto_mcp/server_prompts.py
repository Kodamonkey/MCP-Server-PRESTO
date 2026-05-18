"""MCP prompt registration for ``presto_mcp.server``."""

from __future__ import annotations

from typing import Any

from .prompts import (
    build_explain_failed_run,
    build_fold_known_candidate_plan,
    build_fold_qc_plan,
    build_generate_candidate_report_plan,
    build_inspect_observation_plan,
    build_periodic_advanced_search_plan,
    build_periodic_search_plan,
    build_prepare_filterbank_plan,
    build_rfi_mitigation_plan,
    build_single_pulse_full_plan,
    build_single_pulse_search_plan,
    build_tool_selection_guide,
)


def _prompt_inspect_observation_plan(input_file: str, goal: str | None = None) -> str:
    return build_inspect_observation_plan(input_file, goal=goal)


def _prompt_single_pulse_search_plan(
    input_file: str,
    dm_low: float | None = None,
    dm_high: float | None = None,
    threshold: float | None = None,
) -> str:
    return build_single_pulse_search_plan(
        input_file, dm_low=dm_low, dm_high=dm_high, threshold=threshold
    )


def _prompt_periodic_search_plan(
    input_file: str,
    dm_low: float | None = None,
    dm_high: float | None = None,
    zmax: int | None = None,
) -> str:
    return build_periodic_search_plan(
        input_file, dm_low=dm_low, dm_high=dm_high, zmax=zmax
    )


def _prompt_fold_known_candidate_plan(
    input_file: str, period_seconds: float, dm: float
) -> str:
    return build_fold_known_candidate_plan(input_file, period_seconds, dm)


def _prompt_explain_failed_run(run_id: str) -> str:
    return build_explain_failed_run(run_id)


def _prompt_generate_candidate_report_plan(run_id: str | None = None) -> str:
    return build_generate_candidate_report_plan(run_id)


def _prompt_prepare_filterbank_plan(input_file: str, goal: str | None = None) -> str:
    return build_prepare_filterbank_plan(input_file, goal=goal)


def _prompt_rfi_mitigation_plan(
    input_file: str, existing_rfifind_run_id: str | None = None
) -> str:
    return build_rfi_mitigation_plan(
        input_file, existing_rfifind_run_id=existing_rfifind_run_id
    )


def _prompt_fold_qc_plan(pfd_file: str, goal: str | None = None) -> str:
    return build_fold_qc_plan(pfd_file, goal=goal)


def _prompt_periodic_advanced_search_plan(
    input_file: str, binary_search: bool = False
) -> str:
    return build_periodic_advanced_search_plan(input_file, binary_search=binary_search)


def _prompt_single_pulse_full_plan(
    input_file: str,
    dm_low: float | None = None,
    dm_high: float | None = None,
) -> str:
    return build_single_pulse_full_plan(input_file, dm_low=dm_low, dm_high=dm_high)


def _prompt_tool_selection_guide(task: str) -> str:
    return build_tool_selection_guide(task)


def register_prompts(mcp: Any) -> None:
    mcp.prompt(
        name="presto.inspect_observation_plan",
        description=(
            "Guide the model through inspecting one observation file with "
            "presto.readfile and reporting key metadata. No heavy search is run."
        ),
    )(_prompt_inspect_observation_plan)
    mcp.prompt(
        name="presto.single_pulse_search_plan",
        description=(
            "Conceptual single-pulse search pipeline (readfile -> rfifind -> ddplan "
            "-> prepsubband/prepdata -> single_pulse_search -> rrattrap -> make_spd -> "
            "plot_spd -> waterfaller). Guidance only; tools must be called by client."
        ),
    )(_prompt_single_pulse_search_plan)
    mcp.prompt(
        name="presto.periodic_search_plan",
        description=(
            "Conceptual periodic / acceleration search pipeline (readfile -> rfifind "
            "-> ddplan -> prepdata/prepsubband -> realfft -> zapbirds -> accelsearch -> "
            "sifting -> prepfold -> get_toas). Guidance only."
        ),
    )(_prompt_periodic_search_plan)
    mcp.prompt(
        name="presto.fold_known_candidate_plan",
        description=(
            "Guide the model through folding a known (period, DM) candidate with "
            "presto.prepfold and optionally computing TOAs."
        ),
    )(_prompt_fold_known_candidate_plan)
    mcp.prompt(
        name="presto.explain_failed_run",
        description=(
            "Guide the model through diagnosing a failed run via manifest + stdout "
            "+ stderr, classifying the failure mode and suggesting one next action."
        ),
    )(_prompt_explain_failed_run)
    mcp.prompt(
        name="presto.generate_candidate_report_plan",
        description=(
            "Guide the model through summarising candidate evidence across one or "
            "more runs. Strictly distinguishes artifact / noise / candidate / "
            "detection; does not assert scientific confirmations."
        ),
    )(_prompt_generate_candidate_report_plan)
    mcp.prompt(
        name="presto.prepare_filterbank_plan",
        description=(
            "Guide the model through data preparation (readfile -> psrfits2fil / "
            "fb_truncate / downsample_filterbank as needed). No search is launched."
        ),
    )(_prompt_prepare_filterbank_plan)
    mcp.prompt(
        name="presto.rfi_mitigation_plan",
        description=(
            "Guide the model through RFI mitigation: rfifind -> rfifind_stats -> "
            "weights_to_ignorechan / makezaplist -> zapbirds, and how to use mask "
            "vs zaplist vs ignorechan."
        ),
    )(_prompt_rfi_mitigation_plan)
    mcp.prompt(
        name="presto.fold_qc_plan",
        description=(
            "Guide the model through quality-checking a folded .pfd: inspect "
            ".bestprof/.ps/.png, optionally pfd2png / pfdzap / get_toas / "
            "sum_profiles. Refuses scientific claims without artifact evidence."
        ),
    )(_prompt_fold_qc_plan)
    mcp.prompt(
        name="presto.periodic_advanced_search_plan",
        description=(
            "Guide the model through the periodic-search pipeline plus advanced "
            "add-ons (fourier_fold for known candidates; search_bin for binary "
            "orbital sidebands when binary_search=true)."
        ),
    )(_prompt_periodic_advanced_search_plan)
    mcp.prompt(
        name="presto.single_pulse_full_plan",
        description=(
            "Guide the model through the full single-pulse pipeline (readfile -> "
            "rfifind -> rfifind_stats -> ddplan -> prepsubband -> single_pulse_search "
            "-> rrattrap -> make_spd -> plot_spd -> waterfaller). Suggests fb_truncate "
            "for debugging large inputs."
        ),
    )(_prompt_single_pulse_full_plan)
    mcp.prompt(
        name="presto.tool_selection_guide",
        description=(
            "Categorized index mapping a free-form task description to the right "
            "typed tool(s): data prep / RFI / dedispersion / periodic search / "
            "single-pulse / folding / timing / visualization / debugging / "
            "advanced. Flags experimental tools explicitly."
        ),
    )(_prompt_tool_selection_guide)
