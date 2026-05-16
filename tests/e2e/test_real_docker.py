"""End-to-end tests that drive real PRESTO inside real Docker.

Skipped unless ``--run-e2e`` is passed. Required preconditions:

  * ``docker`` on PATH and Docker Desktop / engine running.
  * Image ``alex88ridolfi/presto5:png`` pulled.
  * ``data/57762_12049_J0532+3305_000022.fil`` present in the repo's ``data/``.

Tests use the repo's real ``Settings`` (loaded from environment + .env). They
write actual artifacts under ``runs/<id>/`` and DO NOT clean them up — that's
intentional so manifests stay inspectable after the test session.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from presto_mcp.config import get_settings
from presto_mcp.docker_backend import DockerBackend
from presto_mcp.errors import DockerInvocationError
from presto_mcp.manifest import load_manifest
from presto_mcp.models import RunStatus
from presto_mcp.tools.readfile import run_readfile
from presto_mcp.tools.rfifind import run_rfifind

REAL_INPUT = "57762_12049_J0532+3305_000022.fil"

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="module")
def real_backend_and_settings():
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


def test_e2e_readfile_real_J0532(real_backend_and_settings) -> None:
    backend, s = real_backend_and_settings
    result = run_readfile(REAL_INPUT, backend=backend, settings=s)
    assert result.status == RunStatus.SUCCESS, result.error
    assert result.result is not None
    md = result.result
    assert md.file_format == "SIGPROC filterbank"
    assert md.source_name == "J0532+3305"
    assert md.num_channels == 672
    assert md.central_freq_mhz == pytest.approx(1564.25)
    # Manifest persisted with the digest if Docker reported one.
    m = load_manifest(s.runs_dir / result.run_id)
    assert m.status == RunStatus.SUCCESS
    assert m.exit_code == 0
    assert "alex88ridolfi/presto5" in m.image
    assert m.presto_argv == ["readfile", f"/data/{REAL_INPUT}"]


def test_e2e_rfifind_real_J0532(real_backend_and_settings) -> None:
    backend, s = real_backend_and_settings
    result = run_rfifind(REAL_INPUT, backend=backend, time=2.0, settings=s)
    assert result.status == RunStatus.SUCCESS, result.error
    assert result.result is not None
    summary = result.result

    # The 3 mandatory artifacts.
    artifacts_dir = s.runs_dir / result.run_id / "artifacts"
    assert any(p.suffix == ".mask" for p in artifacts_dir.iterdir())
    assert any(p.suffix == ".rfi" for p in artifacts_dir.iterdir())
    assert any(p.suffix == ".stats" for p in artifacts_dir.iterdir())
    assert summary.mask_file is not None
    assert summary.mask_file.endswith(".mask")
    # rfifind on this 60-second observation should find at least some RFI.
    assert summary.num_intervals is not None and summary.num_intervals > 0

    # Resource URIs sane.
    assert result.manifest_uri.endswith("/manifest")
    assert any(uri.endswith(".mask") for uri in result.artifact_uris)


def test_e2e_path_traversal_rejected_before_docker(real_backend_and_settings) -> None:
    """A bad path must never reach Docker — assert the security boundary."""
    backend, s = real_backend_and_settings
    from presto_mcp.errors import PathSecurityError

    with pytest.raises(PathSecurityError):
        run_readfile("../escape.fil", backend=backend, settings=s)


def test_e2e_artifacts_under_runs_dir(real_backend_and_settings) -> None:
    """All produced artifacts must live under runs/<id>/artifacts. Nowhere else."""
    backend, s = real_backend_and_settings
    result = run_rfifind(REAL_INPUT, backend=backend, time=2.0, settings=s)
    assert result.status == RunStatus.SUCCESS, result.error
    run_dir: Path = s.runs_dir / result.run_id
    # Everything written by the container should be inside artifacts/. The
    # run dir itself contains only manifest.json, stdout.log, stderr.log,
    # and the artifacts/ subdir.
    children = {p.name for p in run_dir.iterdir()}
    assert "manifest.json" in children
    assert "stdout.log" in children
    assert "stderr.log" in children
    assert "artifacts" in children
    extras = children - {"manifest.json", "stdout.log", "stderr.log", "artifacts"}
    assert not extras, f"unexpected files in run dir: {extras}"
