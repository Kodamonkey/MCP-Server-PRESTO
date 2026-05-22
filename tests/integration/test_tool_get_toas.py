"""Integration test for get_toas with FakeDockerBackend."""

from __future__ import annotations

from pathlib import Path

import pytest

from presto_mcp.config import Settings
from presto_mcp.errors import PathSecurityError, PolicyViolationError
from presto_mcp.manifest import load_manifest
from presto_mcp.models import RunStatus
from presto_mcp.tools.get_toas import run_get_toas
from tests.fakes.fake_docker_backend import FakeDockerBackend, FakeResponse

PRIOR_RUN_ID = "20260517T120000Z-EEEEEE"

_TOAS_STDOUT = """\
Reading template 'sample.gaussians' ...
Loaded 4 components.
FORMAT 1
 prep.pfd  1564.250000  58849.123456789012345  0.10  gbt
 prep.pfd  1564.250000  58849.123456789012346  0.12  gbt
Done.
"""


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    data = tmp_path / "data"
    data.mkdir()
    (data / "sample.gaussians").write_text("gauss 0 0.5 0.1\n")

    runs = tmp_path / "runs"
    prior = runs / PRIOR_RUN_ID / "artifacts"
    prior.mkdir(parents=True)
    (prior / "prep.pfd").write_bytes(b"P")
    return Settings(
        image="alex88ridolfi/presto5:png",
        data_dir=data.resolve(),
        runs_dir=runs.resolve(),
        outputs_dir=(tmp_path / "outputs").resolve(),
        default_cpus=2.0, default_memory_mb=1024, default_timeout_s=60,
        network="none", skip_healthcheck=True,
    )


def test_get_toas_argv_and_parse(settings: Settings) -> None:
    backend = FakeDockerBackend(
        responses={
            "get_TOAs.py": FakeResponse(stdout=_TOAS_STDOUT, status=RunStatus.SUCCESS)
        }
    )
    result = run_get_toas(
        f"{PRIOR_RUN_ID}/artifacts/prep.pfd",
        "sample.gaussians",
        backend=backend,
        num_subints=2, num_subbands=4,
        settings=settings,
    )
    assert result.status == RunStatus.SUCCESS
    assert result.result is not None
    assert result.result.num_toas == 2
    assert result.result.num_subints == 2
    assert result.result.num_subbands == 4

    argv = backend.calls[0].invocation.argv
    assert "get_TOAs.py" in argv
    assert "-g" in argv and "/data/sample.gaussians" in argv
    assert argv[argv.index("-n") + 1] == "2"
    assert argv[argv.index("-s") + 1] == "4"
    pfd_container = f"/runs/{PRIOR_RUN_ID}/artifacts/prep.pfd"
    assert pfd_container in argv

    # /runs mounted ro.
    mounts = [a for a in argv if a.startswith("type=bind,") and "dst=/runs" in a]
    assert len(mounts) == 1
    assert mounts[0].endswith(",readonly")

    m = load_manifest(settings.runs_dir / result.run_id)
    assert m.tool == "get_toas"
    assert m.container_inputs["input_file"] == pfd_container
    assert m.container_inputs["extra_input_0"] == "/data/sample.gaussians"


def test_get_toas_accepts_numeric_gaussian_width(settings: Settings) -> None:
    backend = FakeDockerBackend(
        responses={
            "get_TOAs.py": FakeResponse(stdout=_TOAS_STDOUT, status=RunStatus.SUCCESS)
        }
    )
    result = run_get_toas(
        f"{PRIOR_RUN_ID}/artifacts/prep.pfd",
        backend=backend,
        gaussian_width=0.1,
        settings=settings,
    )
    assert result.status == RunStatus.SUCCESS
    assert result.result is not None
    assert result.result.template_file == "gaussian_width=0.1"

    argv = backend.calls[0].invocation.argv
    assert argv[argv.index("-g") + 1] == "0.1"
    m = load_manifest(settings.runs_dir / result.run_id)
    assert "extra_input_0" not in m.container_inputs


def test_get_toas_requires_one_template_source(settings: Settings) -> None:
    backend = FakeDockerBackend()
    with pytest.raises(PolicyViolationError):
        run_get_toas(
            f"{PRIOR_RUN_ID}/artifacts/prep.pfd",
            backend=backend,
            settings=settings,
        )
    with pytest.raises(PolicyViolationError):
        run_get_toas(
            f"{PRIOR_RUN_ID}/artifacts/prep.pfd",
            "sample.gaussians",
            backend=backend,
            gaussian_width=0.1,
            settings=settings,
        )


@pytest.mark.parametrize("nsi", [0, 5000])
def test_get_toas_rejects_bad_subints(settings: Settings, nsi: int) -> None:
    backend = FakeDockerBackend()
    with pytest.raises(PolicyViolationError):
        run_get_toas(
            f"{PRIOR_RUN_ID}/artifacts/prep.pfd",
            "sample.gaussians",
            backend=backend, num_subints=nsi, num_subbands=1,
            settings=settings,
        )


def test_get_toas_rejects_bad_template_path(settings: Settings) -> None:
    backend = FakeDockerBackend()
    with pytest.raises(PathSecurityError):
        run_get_toas(
            f"{PRIOR_RUN_ID}/artifacts/prep.pfd",
            "../escape.gaussians",
            backend=backend, settings=settings,
        )
