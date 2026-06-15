"""Unit tests for run_label helpers."""

from __future__ import annotations

import pytest

from presto_mcp.run_label import observation_basename, run_label


@pytest.mark.parametrize(
    ("inputs", "expected"),
    [
        ({"input_file": "57762_12049_J0532+3305_000022.fil"}, "57762_12049_J0532+3305_000022"),
        ({"input_file": "sub/dir/obs.fits"}, "obs"),
        ({"input_file": "obs.fits.gz"}, "obs"),
        ({"input_file": r"D:\data\obs.fil"}, "obs"),
        ({"input_file": "noext"}, "noext"),
        ({}, None),
        ({"input_file": ""}, None),
        (None, None),
    ],
)
def test_observation_basename(inputs, expected) -> None:
    assert observation_basename(inputs) == expected


def test_run_label_with_input() -> None:
    label = run_label("rfifind", {"input_file": "J0532+3305.fil"})
    assert label == "J0532+3305__rfifind"


def test_run_label_without_input() -> None:
    assert run_label("ddplan", {}) == "ddplan"
    assert run_label("ddplan", None) == "ddplan"
