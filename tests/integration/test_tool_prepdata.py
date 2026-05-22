"""Integration test for prepdata with FakeDockerBackend."""

from __future__ import annotations

from pathlib import Path

import pytest

from presto_mcp.config import Settings
from presto_mcp.errors import PolicyViolationError
from presto_mcp.manifest import load_manifest
from presto_mcp.models import RunStatus
from presto_mcp.tools.prepdata import run_prepdata
from tests.fakes.fake_docker_backend import FakeDockerBackend, FakeResponse

PRIOR_RUN_ID = "20260517T120000Z-MMMMMM"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    data = tmp_path / "data"
    data.mkdir()
    (data / "input.fil").write_bytes(b"\x00" * 16)
    (data / "noise.mask").write_bytes(b"M")

    runs = tmp_path / "runs"
    prior = runs / PRIOR_RUN_ID / "artifacts"
    prior.mkdir(parents=True)
    # Mock an rfifind output set: PRESTO needs all five companions next to .mask.
    for ext in (".mask", ".bytemask", ".inf", ".rfi", ".stats"):
        (prior / f"rfi_rfifind{ext}").write_bytes(b"X")

    return Settings(
        image="alex88ridolfi/presto5:png",
        data_dir=data.resolve(),
        runs_dir=runs.resolve(),
        outputs_dir=(tmp_path / "outputs").resolve(),
        default_cpus=2.0,
        default_memory_mb=1024,
        default_timeout_s=60,
        network="none",
        skip_healthcheck=True,
    )


def test_prepdata_argv_and_artifacts(settings: Settings) -> None:
    backend = FakeDockerBackend(
        responses={
            "prepdata": FakeResponse(
                stdout="Total points (N) :  1024\nSample dt (s)    :  6.4e-05\nDone.\n",
                status=RunStatus.SUCCESS,
                artifacts={"prep.dat": b"D", "prep.inf": b"I"},
            )
        }
    )
    result = run_prepdata(
        "input.fil", 56.78,
        backend=backend, settings=settings,
    )

    assert result.status == RunStatus.SUCCESS
    assert result.result is not None
    assert result.result.dm == 56.78
    assert result.result.output_prefix == "prep"
    assert result.result.dat_file == "prep.dat"
    assert result.result.num_samples == 1024

    argv = backend.calls[0].invocation.argv
    assert "prepdata" in argv
    assert "-dm" in argv
    assert "56.78" in argv
    assert "/outputs/artifacts/prep" in argv
    assert argv[-1] == "/data/input.fil"

    m = load_manifest(settings.runs_dir / result.run_id)
    assert m.tool == "prepdata"
    assert m.inputs["dm"] == "56.78"


def test_prepdata_with_mask_file(settings: Settings) -> None:
    backend = FakeDockerBackend(
        responses={
            "prepdata": FakeResponse(
                stdout="ok\n", status=RunStatus.SUCCESS,
                artifacts={"prep.dat": b"D"},
            )
        }
    )
    result = run_prepdata(
        "input.fil", 10.0, mask_file="noise.mask",
        backend=backend, settings=settings,
    )
    assert result.status == RunStatus.SUCCESS
    argv = backend.calls[0].invocation.argv
    assert "-mask" in argv
    assert "/data/noise.mask" in argv

    m = load_manifest(settings.runs_dir / result.run_id)
    assert m.container_inputs["extra_input_0"] == "/data/noise.mask"


def test_prepdata_with_mask_from_prior_run(settings: Settings) -> None:
    """Mask path of the form ``<run_id>/artifacts/<file>.mask`` should be
    resolved against ``RUNS_DIR`` and the ``/runs`` mount must appear in the
    Docker argv. This is the fix for the rfifind→prepdata chain where copying
    rfifind output into DATA_DIR was previously required."""
    backend = FakeDockerBackend(
        responses={
            "prepdata": FakeResponse(
                stdout="ok\n", status=RunStatus.SUCCESS,
                artifacts={"prep.dat": b"D"},
            )
        }
    )
    mask_arg = f"{PRIOR_RUN_ID}/artifacts/rfi_rfifind.mask"
    result = run_prepdata(
        "input.fil", 10.0, mask_file=mask_arg,
        backend=backend, settings=settings,
    )
    assert result.status == RunStatus.SUCCESS

    argv = backend.calls[0].invocation.argv
    expected_container_mask = f"/runs/{PRIOR_RUN_ID}/artifacts/rfi_rfifind.mask"
    assert "-mask" in argv
    assert expected_container_mask in argv
    # The read-only /runs mount must be present so PRESTO can read the mask
    # companion files alongside it.
    runs_mounts = [
        a for a in argv
        if a.startswith("type=bind,") and "dst=/runs" in a and a.endswith(",readonly")
    ]
    assert len(runs_mounts) == 1

    m = load_manifest(settings.runs_dir / result.run_id)
    assert m.container_inputs["extra_input_0"] == expected_container_mask
    assert m.inputs["mask_file"] == mask_arg


@pytest.mark.parametrize("bad_dm", [-0.001, 10_001.0])
def test_prepdata_rejects_bad_dm(settings: Settings, bad_dm: float) -> None:
    backend = FakeDockerBackend()
    with pytest.raises(PolicyViolationError):
        run_prepdata("input.fil", bad_dm, backend=backend, settings=settings)
    assert backend.calls == []
