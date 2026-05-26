"""E2E test: DDplan.py inside the real PRESTO container.

DDplan is pure compute and needs no input file. Skipped unless --run-e2e.
"""

from __future__ import annotations

import shutil

import pytest

from presto_mcp.config import get_settings
from presto_mcp.docker_backend import DockerBackend
from presto_mcp.errors import DockerInvocationError
from presto_mcp.models import RunStatus
from presto_mcp.tools.ddplan import run_ddplan

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="module")
def backend_and_settings():
    if shutil.which("docker") is None:
        pytest.skip("docker not available")
    try:
        backend = DockerBackend()
    except DockerInvocationError as e:
        pytest.skip(str(e))
    s = get_settings()
    # ddplan is pure-compute: the executor skips the /data mount when no
    # input is needed, and create_run_dir auto-creates runs_dir. No extra
    # filesystem setup required, even on fresh CI checkouts.
    return backend, s


def test_e2e_ddplan(backend_and_settings) -> None:
    backend, s = backend_and_settings
    result = run_ddplan(
        backend=backend,
        dm_low=0.0, dm_high=50.0,
        freq_mhz=1564.25, bw_mhz=336.0,
        num_channels=672, sample_time_us=64.0,
        settings=s,
    )
    assert result.status == RunStatus.SUCCESS, result.error
    assert result.result is not None
    assert len(result.result.passes) >= 1
    assert result.result.num_dms > 0
