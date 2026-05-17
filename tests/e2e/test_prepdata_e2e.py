"""E2E test: prepdata on real data inside real Docker."""

from __future__ import annotations

import shutil

import pytest

from presto_mcp.config import get_settings
from presto_mcp.docker_backend import DockerBackend
from presto_mcp.errors import DockerInvocationError
from presto_mcp.models import RunStatus
from presto_mcp.tools.prepdata import run_prepdata

pytestmark = pytest.mark.e2e

REAL_INPUT = "57762_12049_J0532+3305_000022.fil"


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


def test_e2e_prepdata_real(backend_and_settings) -> None:
    backend, s = backend_and_settings
    result = run_prepdata(
        REAL_INPUT, dm=56.78,
        backend=backend, settings=s,
    )
    assert result.status == RunStatus.SUCCESS, result.error
    assert result.result is not None
    assert result.result.dat_file is not None
    assert result.result.dat_file.endswith(".dat")
    assert result.result.inf_file is not None
    # produced artifacts under runs/<id>/artifacts/
    art_dir = s.runs_dir / result.run_id / "artifacts"
    assert any(p.suffix == ".dat" for p in art_dir.iterdir())
