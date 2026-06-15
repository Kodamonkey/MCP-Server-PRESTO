"""Round-trip tests for the SIGPROC filterbank generator.

No Docker needed: write a header, read it back, assert the values survive.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.fixtures.sigproc import (
    DEFAULT_PARAMS,
    FilterbankParams,
    read_header,
    write_filterbank,
)


def test_write_then_read_roundtrips(tmp_path: Path) -> None:
    path = write_filterbank(tmp_path / "fake.fil")
    h = read_header(path)

    p = DEFAULT_PARAMS
    assert h["source_name"] == p.source_name
    assert h["telescope_id"] == p.telescope_id
    assert h["nchans"] == p.nchans
    assert h["nbits"] == p.nbits
    assert h["nifs"] == p.nifs
    assert h["tsamp"] == pytest.approx(p.tsamp)
    assert h["fch1"] == pytest.approx(p.fch1)
    assert h["foff"] == pytest.approx(p.foff)


def test_data_section_size_matches_params(tmp_path: Path) -> None:
    p = FilterbankParams(nchans=4, nsamples=10, nifs=1, nbits=8)
    path = write_filterbank(tmp_path / "small.fil", p)
    h = read_header(path)
    assert h["_data_bytes"] == p.nchans * p.nsamples * p.nifs


def test_file_is_small(tmp_path: Path) -> None:
    path = write_filterbank(tmp_path / "fake.fil")
    assert path.stat().st_size < 4096  # stays a few KB, fine to regenerate anywhere


def test_generation_is_deterministic(tmp_path: Path) -> None:
    a = write_filterbank(tmp_path / "a.fil")
    b = write_filterbank(tmp_path / "b.fil")
    assert a.read_bytes() == b.read_bytes()


def test_nbits_other_than_8_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="nbits=8"):
        write_filterbank(tmp_path / "x.fil", FilterbankParams(nbits=16))
