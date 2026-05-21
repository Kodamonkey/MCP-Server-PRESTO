"""Unit tests for policy validators (data-prep / RFI / advanced tools)."""

from __future__ import annotations

import pytest

from presto_mcp import policies
from presto_mcp.errors import PolicyViolationError

# -- downsample factor -------------------------------------------------------

def test_check_downsample_factor_ok() -> None:
    assert policies.check_downsample_factor(2) == 2
    assert policies.check_downsample_factor(1024) == 1024


@pytest.mark.parametrize("bad", [0, 1, 1025, -1])
def test_check_downsample_factor_rejects(bad: int) -> None:
    with pytest.raises(PolicyViolationError):
        policies.check_downsample_factor(bad)


def test_check_downsample_factor_rejects_non_int() -> None:
    with pytest.raises(PolicyViolationError):
        policies.check_downsample_factor(2.5)  # type: ignore[arg-type]


# -- truncate sample / seconds ----------------------------------------------

def test_check_truncate_samples_ok() -> None:
    assert policies.check_truncate_start_sample(0) == 0
    assert policies.check_truncate_num_samples(1_000_000) == 1_000_000


@pytest.mark.parametrize("bad", [-1, -1000])
def test_check_truncate_start_sample_rejects(bad: int) -> None:
    with pytest.raises(PolicyViolationError):
        policies.check_truncate_start_sample(bad)


@pytest.mark.parametrize("bad", [0, -1, 10**11])
def test_check_truncate_num_samples_rejects(bad: int) -> None:
    with pytest.raises(PolicyViolationError):
        policies.check_truncate_num_samples(bad)


def test_check_truncate_seconds_ok() -> None:
    assert policies.check_truncate_start_s(0.0) == 0.0
    assert policies.check_truncate_duration_s(1.0) == 1.0


@pytest.mark.parametrize("bad", [-1.0, 100_000.0])
def test_check_truncate_start_s_rejects(bad: float) -> None:
    with pytest.raises(PolicyViolationError):
        policies.check_truncate_start_s(bad)


@pytest.mark.parametrize("bad", [0.0, -1.0, 100_000.0])
def test_check_truncate_duration_s_rejects(bad: float) -> None:
    with pytest.raises(PolicyViolationError):
        policies.check_truncate_duration_s(bad)


# -- profile file count ------------------------------------------------------

def test_check_profile_file_count_ok() -> None:
    assert policies.check_profile_file_count(["a"]) == ["a"]


def test_check_profile_file_count_rejects_empty() -> None:
    with pytest.raises(PolicyViolationError):
        policies.check_profile_file_count([])


def test_check_profile_file_count_rejects_too_many() -> None:
    with pytest.raises(PolicyViolationError):
        policies.check_profile_file_count(["x"] * (policies.PROFILE_FILE_COUNT_MAX + 1))


# -- fourier_fold period / freq xor -----------------------------------------

def test_fourier_fold_requires_exactly_one() -> None:
    with pytest.raises(PolicyViolationError):
        policies.check_fourier_fold_period_or_freq(None, None)
    with pytest.raises(PolicyViolationError):
        policies.check_fourier_fold_period_or_freq(0.1, 10.0)


def test_fourier_fold_accepts_period_only() -> None:
    p, f = policies.check_fourier_fold_period_or_freq(0.1, None)
    assert p == 0.1 and f is None


def test_fourier_fold_accepts_freq_only() -> None:
    p, f = policies.check_fourier_fold_period_or_freq(None, 50.0)
    assert p is None and f == 50.0


# -- pfdzap commands ---------------------------------------------------------

def test_pfdzap_commands_ok() -> None:
    assert policies.check_pfdzap_commands(["0:10", "60:80"]) == ["0:10", "60:80"]


def test_pfdzap_commands_none() -> None:
    assert policies.check_pfdzap_commands(None) is None


@pytest.mark.parametrize(
    "bad",
    [
        ["rm -rf /"],
        ["0-10"],
        ["abc:def"],
        ["10:"],
        [":10"],
        ["0:10; echo x"],
    ],
)
def test_pfdzap_commands_rejects_bad_tokens(bad: list[str]) -> None:
    with pytest.raises(PolicyViolationError):
        policies.check_pfdzap_commands(bad)


def test_pfdzap_commands_rejects_too_many() -> None:
    with pytest.raises(PolicyViolationError):
        policies.check_pfdzap_commands(["0:1"] * (policies.PFDZAP_TOKEN_MAX + 1))


# -- search_bin freq range ---------------------------------------------------

def test_search_bin_none_pair_ok() -> None:
    assert policies.check_search_bin_freq_range(None, None) == (None, None)


def test_search_bin_band_ok() -> None:
    lo, hi = policies.check_search_bin_freq_range(1.0, 100.0)
    assert lo == 1.0 and hi == 100.0


@pytest.mark.parametrize(
    "lo, hi",
    [
        (10.0, 5.0),
        (5.0, 5.0),
        (-1.0, 5.0),
        (1.0, 6e5),
        (1.0, None),
        (None, 5.0),
    ],
)
def test_search_bin_rejects_bad_band(lo, hi) -> None:
    with pytest.raises(PolicyViolationError):
        policies.check_search_bin_freq_range(lo, hi)


# -- frequency_hz ------------------------------------------------------------

def test_check_frequency_hz_ok() -> None:
    assert policies.check_frequency_hz(10.0) == 10.0


@pytest.mark.parametrize("bad", [0.0, -1.0, 2e9])
def test_check_frequency_hz_rejects(bad: float) -> None:
    with pytest.raises(PolicyViolationError):
        policies.check_frequency_hz(bad)
