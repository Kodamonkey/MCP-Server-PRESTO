"""Prompt builders are pure text — no Docker, no PRESTO, no I/O."""

from __future__ import annotations

import inspect

import pytest

from presto_mcp import prompts


@pytest.mark.parametrize(
    "fn, args, expected_tools",
    [
        (
            prompts.build_inspect_observation_plan,
            ("data/obs.fil",),
            ["presto.readfile"],
        ),
        (
            prompts.build_single_pulse_search_plan,
            ("data/obs.fil",),
            [
                "presto.readfile",
                "presto.rfifind",
                "presto.ddplan",
                "presto.prepsubband",
                "presto.prepdata",
                "presto.single_pulse_search",
                "presto.rrattrap",
                "presto.make_spd",
                "presto.plot_spd",
                "presto.waterfaller",
            ],
        ),
        (
            prompts.build_periodic_search_plan,
            ("data/obs.fil",),
            [
                "presto.readfile",
                "presto.rfifind",
                "presto.ddplan",
                "presto.prepdata",
                "presto.prepsubband",
                "presto.realfft",
                "presto.zapbirds",
                "presto.accelsearch",
                "presto.sifting",
                "presto.prepfold",
                "presto.get_toas",
            ],
        ),
        (
            prompts.build_fold_known_candidate_plan,
            ("data/obs.fil", 0.0337, 56.7),
            ["presto.readfile", "presto.prepfold", "presto.get_toas"],
        ),
        (
            prompts.build_explain_failed_run,
            ("20260516T143052Z-K7QM3A",),
            ["presto.get_run_manifest"],
        ),
        (
            prompts.build_generate_candidate_report_plan,
            (None,),
            ["presto.list_runs", "presto.get_run_manifest", "presto.summarize_run"],
        ),
        (
            prompts.build_candidate_review_plan,
            (None,),
            [
                "presto.list_runs",
                "presto.summarize_run",
                "presto.inspect_artifacts",
                "presto.pfd2png",
                "presto.waterfaller",
                "presto.compare_periods",
                "presto.binary_info",
                "presto.compile_candidate_report_pdf",
            ],
        ),
        (
            prompts.build_prepare_filterbank_plan,
            ("data/obs.fits",),
            [
                "presto.readfile",
                "presto.psrfits2fil",
                "presto.fb_truncate",
                "presto.downsample_filterbank",
            ],
        ),
        (
            prompts.build_rfi_mitigation_plan,
            ("data/obs.fil",),
            [
                "presto.rfifind",
                "presto.rfifind_stats",
                "presto.weights_to_ignorechan",
                "presto.makezaplist",
                "presto.zapbirds",
            ],
        ),
        (
            prompts.build_fold_qc_plan,
            ("20260516T143052Z-K7QM3A/artifacts/fold.pfd",),
            [
                "presto.pfd2png",
                "presto.get_toas",
                "presto.sum_profiles",
            ],
        ),
        (
            prompts.build_periodic_advanced_search_plan,
            ("data/obs.fil", True),
            [
                "presto.readfile",
                "presto.accelsearch",
                "presto.sifting",
                "presto.prepfold",
                "presto.search_bin",
            ],
        ),
        (
            prompts.build_single_pulse_full_plan,
            ("data/obs.fil",),
            [
                "presto.readfile",
                "presto.rfifind",
                "presto.rfifind_stats",
                "presto.single_pulse_search",
                "presto.rrattrap",
                "presto.make_spd",
                "presto.plot_spd",
                "presto.waterfaller",
                "presto.fb_truncate",
            ],
        ),
        (
            prompts.build_tool_selection_guide,
            ("RFI mitigation for an FRB search",),
            [
                "presto.readfile",
                "presto.rfifind",
                "presto.zapbirds",
                "presto.prepsubband",
                "presto.accelsearch",
                "presto.single_pulse_search",
                "presto.search_bin",
            ],
        ),
    ],
)
def test_builder_mentions_expected_tools(fn, args, expected_tools) -> None:
    text = fn(*args)
    assert isinstance(text, str)
    assert text.strip()
    for tool in expected_tools:
        assert tool in text, f"{fn.__name__} missing {tool}"


def test_all_builders_include_disclaimer() -> None:
    builders = [
        prompts.build_inspect_observation_plan("x"),
        prompts.build_single_pulse_search_plan("x"),
        prompts.build_periodic_search_plan("x"),
        prompts.build_fold_known_candidate_plan("x", 1.0, 1.0),
        prompts.build_explain_failed_run("20260516T143052Z-K7QM3A"),
        prompts.build_generate_candidate_report_plan(None),
        prompts.build_candidate_review_plan(None),
        prompts.build_prepare_filterbank_plan("x"),
        prompts.build_rfi_mitigation_plan("x"),
        prompts.build_fold_qc_plan("x"),
        prompts.build_periodic_advanced_search_plan("x"),
        prompts.build_single_pulse_full_plan("x"),
        prompts.build_tool_selection_guide("any task"),
    ]
    for text in builders:
        assert "guidance only" in text.lower()
        assert "does not auto-execute" in text.lower()


def test_search_plans_carry_guardrails() -> None:
    sp = prompts.build_single_pulse_search_plan("x")
    pp = prompts.build_periodic_search_plan("x")
    cr = prompts.build_candidate_review_plan(None)
    for text in (sp, pp, cr):
        assert "presto.validate_environment" in text
        assert "taxonomy" in text.lower()
        assert "detection" in text.lower()
    # periodic plan must flag the image-dependent wmax flag
    assert "wmax" in pp
    # single-pulse plan must gate rrattrap on readiness
    assert "presto.singlepulse" in sp
    # candidate review must refuse unilateral scientific confirmation
    assert "human" in cr.lower()


def test_builders_are_pure_functions() -> None:
    # No async, no generators — pure synchronous string builders.
    for name in (
        "build_inspect_observation_plan",
        "build_single_pulse_search_plan",
        "build_periodic_search_plan",
        "build_fold_known_candidate_plan",
        "build_explain_failed_run",
        "build_generate_candidate_report_plan",
        "build_candidate_review_plan",
        "build_prepare_filterbank_plan",
        "build_rfi_mitigation_plan",
        "build_fold_qc_plan",
        "build_periodic_advanced_search_plan",
        "build_single_pulse_full_plan",
        "build_tool_selection_guide",
    ):
        fn = getattr(prompts, name)
        assert callable(fn)
        assert not inspect.iscoroutinefunction(fn)
        assert not inspect.isasyncgenfunction(fn)
