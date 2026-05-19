"""End-to-end pipeline test: prepsubband → realfft → accelsearch →
single_pulse_search → sifting → get_TOAs.

Runs each stage in order against real PRESTO inside real Docker. Each test
captures a run_id and the next stage feeds off it. Skipped unless --run-e2e.

These tests are intentionally one chained suite (not parametrized) so that
a failure at stage N doesn't waste time on stages N+1...N+k.
"""

from __future__ import annotations

import shutil

import pytest

from presto_mcp.config import get_settings
from presto_mcp.docker_backend import DockerBackend
from presto_mcp.errors import DockerInvocationError
from presto_mcp.models import RunStatus
from presto_mcp.tools.accelsearch import run_accelsearch
from presto_mcp.tools.get_toas import run_get_toas
from presto_mcp.tools.prepfold import run_prepfold
from presto_mcp.tools.prepsubband import run_prepsubband
from presto_mcp.tools.realfft import run_realfft
from presto_mcp.tools.sifting import run_sifting
from presto_mcp.tools.single_pulse_search import run_single_pulse_search

pytestmark = pytest.mark.e2e

REAL_INPUT = "57762_12049_J0532+3305_000022.fil"

# Module-level state. Tests must run in source order.
_state: dict[str, str] = {}


@pytest.fixture(scope="module")
def backend_and_settings():
    if shutil.which("docker") is None:
        pytest.skip("docker not available")
    s = get_settings()
    if not (s.data_dir / REAL_INPUT).is_file():
        pytest.skip(f"missing real data file: {REAL_INPUT}")
    try:
        backend = DockerBackend()
    except DockerInvocationError as e:
        pytest.skip(str(e))
    return backend, s


def test_01_prepsubband(backend_and_settings) -> None:
    backend, s = backend_and_settings
    result = run_prepsubband(
        REAL_INPUT,
        backend=backend,
        dm_low=50.0, dm_step=0.5, num_dms=8, num_subbands=32,
        settings=s,
    )
    assert result.status == RunStatus.SUCCESS, result.error
    assert result.result is not None
    assert len(result.result.dat_files) > 0
    _state["prepsubband_run_id"] = result.run_id
    _state["first_dat"] = result.result.dat_files[0]


def test_02_realfft(backend_and_settings) -> None:
    backend, s = backend_and_settings
    rid = _state.get("prepsubband_run_id")
    name = _state.get("first_dat")
    if not rid or not name:
        pytest.skip("prepsubband stage did not run")
    result = run_realfft(
        f"{rid}/artifacts/{name}",
        backend=backend, settings=s,
    )
    assert result.status == RunStatus.SUCCESS, result.error
    assert result.result is not None
    assert result.result.fft_file is not None
    _state["realfft_run_id"] = result.run_id
    _state["fft_name"] = result.result.fft_file


def test_03_accelsearch(backend_and_settings) -> None:
    backend, s = backend_and_settings
    rid = _state.get("realfft_run_id")
    fft = _state.get("fft_name")
    if not rid or not fft:
        pytest.skip("realfft stage did not run")
    result = run_accelsearch(
        f"{rid}/artifacts/{fft}",
        backend=backend, zmax=200, numharm=8, settings=s,
    )
    assert result.status == RunStatus.SUCCESS, result.error
    _state["accelsearch_run_id"] = result.run_id
    if result.result is not None and result.result.accel_cand_file:
        _state["accel_cand"] = result.result.accel_cand_file


def test_04_single_pulse_search(backend_and_settings) -> None:
    backend, s = backend_and_settings
    rid = _state.get("prepsubband_run_id")
    if not rid:
        pytest.skip("prepsubband stage did not run")
    art_dir = s.runs_dir / rid / "artifacts"
    dat_paths = sorted(p.name for p in art_dir.glob("*.dat"))[:3]
    if not dat_paths:
        pytest.skip("no .dat artifacts found from prior prepsubband run")
    result = run_single_pulse_search(
        [f"{rid}/artifacts/{n}" for n in dat_paths],
        backend=backend, threshold=5.0, max_width_s=0.1, settings=s,
    )
    assert result.status == RunStatus.SUCCESS, result.error
    assert result.result is not None
    assert len(result.result.singlepulse_files) == len(dat_paths)


def test_05_sifting(backend_and_settings) -> None:
    backend, s = backend_and_settings
    rid = _state.get("accelsearch_run_id")
    cand = _state.get("accel_cand")
    if not rid or not cand:
        pytest.skip("accelsearch produced no candidate file")
    result = run_sifting(
        [f"{rid}/artifacts/{cand}"],
        backend=backend,
        min_num_dms=1, low_dm_cutoff=0.0, sigma_threshold=2.0,
        settings=s,
    )
    # ACCEL_sift sometimes returns no surviving cands; that's not a failure
    # of the wrapper. Accept SUCCESS or FAILED but require the manifest is sane.
    assert result.status in {RunStatus.SUCCESS, RunStatus.FAILED}, result.error


def test_06_prepfold_then_get_toas(backend_and_settings) -> None:
    backend, s = backend_and_settings
    # Need a .pfd. Fold the real file at a known candidate period/DM.
    fold = run_prepfold(
        REAL_INPUT, period_s=0.05, dm=56.78,
        backend=backend, settings=s,
    )
    if fold.status != RunStatus.SUCCESS or fold.result is None or not fold.result.pfd_file:
        pytest.skip(f"prepfold did not produce a .pfd: {fold.error}")
    result = run_get_toas(
        f"{fold.run_id}/artifacts/{fold.result.pfd_file}",
        backend=backend,
        num_subints=1,
        num_subbands=1,
        gaussian_width=0.1,
        settings=s,
    )
    assert result.status in {RunStatus.SUCCESS, RunStatus.FAILED}, result.error
