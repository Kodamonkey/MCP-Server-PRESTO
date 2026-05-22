"""E2E: modern report bundle over a real PRESTO run on a real data file."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from presto_mcp.config import get_settings
from presto_mcp.docker_backend import DockerBackend
from presto_mcp.errors import DockerInvocationError
from presto_mcp.models import RunStatus
from presto_mcp.tools.readfile import run_readfile
from presto_mcp.tools.reporting import run_generate_modern_report_bundle

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


def test_e2e_report_bundle_real(backend_and_settings) -> None:
    backend, s = backend_and_settings

    # Real PRESTO run: extract observation metadata from the filterbank.
    readfile = run_readfile(REAL_INPUT, backend=backend, settings=s)
    assert readfile.status == RunStatus.SUCCESS, readfile.error

    # Modern reporting layer consolidates that run into a bundle.
    result = run_generate_modern_report_bundle(
        run_ids=[readfile.run_id],
        input_file=REAL_INPUT,
        settings=s,
        wants_report=True,
    )
    out = Path(result.output_dir)
    for name in ("summary.json", "candidates.csv", "report.html", "report.md", "manifest.json"):
        assert (out / name).is_file(), name

    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    obs = summary["observation"]
    # readfile metadata flowed into the modern summary
    assert obs["central_freq_mhz"] is not None
    assert obs["nchans"] is not None

    # raw PRESTO intermediates are never published by default
    assert not any(p.suffix in {".dat", ".fft", ".pfd", ".ps"} for p in out.rglob("*"))
