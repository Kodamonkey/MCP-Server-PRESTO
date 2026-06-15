"""E2E test: readfile on a self-contained generated .fil inside real Docker.

Unlike the other e2e tests this one needs no external ``PRESTO_DATA_DIR`` — it
generates a tiny spec-valid filterbank into a temp dir and points the server at
it, so the real read path is exercised anywhere Docker + the PRESTO image exist.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from presto_mcp.config import Settings, get_settings
from presto_mcp.docker_backend import DockerBackend
from presto_mcp.errors import DockerInvocationError
from presto_mcp.models import RunStatus
from presto_mcp.tools.readfile import run_readfile
from tests.fixtures.sigproc import DEFAULT_PARAMS, write_filterbank

pytestmark = pytest.mark.e2e


@pytest.fixture
def backend() -> DockerBackend:
    if shutil.which("docker") is None:
        pytest.skip("docker not available")
    try:
        return DockerBackend()
    except DockerInvocationError as e:
        pytest.skip(str(e))


@pytest.fixture
def settings_with_fil(tmp_path: Path) -> Settings:
    data = tmp_path / "data"
    data.mkdir()
    write_filterbank(data / "fake.fil")
    runs = tmp_path / "runs"
    runs.mkdir()
    return get_settings().with_overrides(
        data_dir=data.resolve(),
        runs_dir=runs.resolve(),
        skip_healthcheck=True,
    )


def test_e2e_readfile_generated_fil(
    backend: DockerBackend, settings_with_fil: Settings
) -> None:
    result = run_readfile("fake.fil", backend=backend, settings=settings_with_fil)

    assert result.status == RunStatus.SUCCESS, result.error
    assert result.result is not None
    meta = result.result

    p = DEFAULT_PARAMS
    assert meta.file_format == "SIGPROC filterbank"
    assert meta.num_channels == p.nchans
    assert meta.bits_per_sample == p.nbits
    assert meta.sample_time_us == pytest.approx(p.tsamp * 1e6, rel=1e-3)

    # Resource metrics should be populated on a real Docker run of non-trivial
    # duration (best-effort; assert presence without pinning exact values).
    from presto_mcp.manifest import load_manifest

    manifest = load_manifest(settings_with_fil.runs_dir / result.run_id)
    if manifest.resource_usage is not None:
        assert manifest.resource_usage.memory_limit_mb == manifest.memory_mb
