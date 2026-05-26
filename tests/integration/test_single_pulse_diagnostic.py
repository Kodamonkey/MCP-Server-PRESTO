"""Integration test for the composite single_pulse_diagnostic workflow."""

from __future__ import annotations

from pathlib import Path

import pytest

from presto_mcp.config import Settings, set_resolved_container_python
from presto_mcp.models import RunStatus
from presto_mcp.tools.single_pulse_diagnostic import run_single_pulse_diagnostic
from tests.fakes.fake_docker_backend import FakeDockerBackend, FakeResponse


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    data = tmp_path / "data"
    data.mkdir()
    (data / "obs.fil").write_bytes(b"FIL" * 64)
    (data / "obs_rfifind.mask").write_bytes(b"MASK")
    runs = tmp_path / "runs"
    runs.mkdir()

    # Stage prepdata-style prior run with .dat + .inf
    prior = runs / "20260101T000000Z-ABC234" / "artifacts"
    prior.mkdir(parents=True)
    (prior / "sub_DM10.dat").write_bytes(b"DAT")
    (prior / "sub_DM10.inf").write_text(" Sample time (us)    =  64.0\n", encoding="utf-8")

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


def test_single_pulse_diagnostic_chains_four_stages(settings: Settings) -> None:
    """Full chain runs sps -> rrattrap -> make_spd -> plot_spd and aggregates results."""
    set_resolved_container_python("python3")

    # FakeDockerBackend returns the same response for every container call; we
    # arrange artifact files keyed by tool by inspecting argv.
    def _route(name: str) -> FakeResponse:
        return _RESPONSES[name]

    _RESPONSES = {
        "single_pulse_search.py": FakeResponse(
            stdout="sps ok\n",
            status=RunStatus.SUCCESS,
            artifacts={"sub_DM10.singlepulse": b"# DM Sigma Time Sample Downfact\n"},
        ),
        "rrattrap.py": FakeResponse(
            stdout="rrattrap ok\n",
            status=RunStatus.SUCCESS,
            artifacts={
                "groups.txt": (
                    b"# groups\nRank: 1\nCentre DM: 10.0\nMax Sigma: 9.0\n"
                ),
            },
        ),
        "make_spd.py": FakeResponse(
            stdout="make_spd ok\n",
            status=RunStatus.SUCCESS,
            artifacts={"spd_DM10_t12_RANK1.spd": b"SPD"},
        ),
        "plot_spd.py": FakeResponse(
            stdout="plot_spd ok\n",
            status=RunStatus.SUCCESS,
            artifacts={"spdplot_DM10.png": b"\x89PNG"},
        ),
    }

    backend = FakeDockerBackend(
        responses=_RESPONSES,
        probe_responses={
            "which:rrattrap.py": FakeResponse(
                stdout="/usr/local/bin/rrattrap.py\n", status=RunStatus.SUCCESS
            ),
            "module:presto.singlepulse": FakeResponse(
                stdout="", status=RunStatus.SUCCESS
            ),
        },
    )

    prior_run = "20260101T000000Z-ABC234"
    result, status = run_single_pulse_diagnostic(
        dat_files=[f"{prior_run}/artifacts/sub_DM10.dat"],
        inf_file=f"{prior_run}/artifacts/sub_DM10.inf",
        raw_file="obs.fil",
        backend=backend,
        mask_file="obs_rfifind.mask",
        apply_mask=True,
        threshold=5.0,
        max_width_s=0.1,
        settings=settings,
    )

    assert status == RunStatus.SUCCESS, result.model_dump()
    stage_names = [s.stage for s in result.stages]
    assert stage_names[:3] == ["single_pulse_search", "rrattrap", "make_spd"]
    assert "plot_spd" in stage_names
    assert result.singlepulse_files, "expected at least one singlepulse file"
    assert result.groups_file is not None
    assert result.spd_files, "make_spd must produce at least one .spd"
    assert result.plot_pngs, "plot_spd must produce at least one PNG"


def test_single_pulse_diagnostic_short_circuits_on_failure(settings: Settings) -> None:
    """When single_pulse_search fails, downstream stages are skipped."""
    set_resolved_container_python("python3")
    backend = FakeDockerBackend(
        responses={
            "single_pulse_search.py": FakeResponse(
                stdout="",
                status=RunStatus.FAILED,
                exit_code=1,
                stderr="boom",
            ),
        }
    )
    prior_run = "20260101T000000Z-ABC234"
    result, status = run_single_pulse_diagnostic(
        dat_files=[f"{prior_run}/artifacts/sub_DM10.dat"],
        inf_file=f"{prior_run}/artifacts/sub_DM10.inf",
        raw_file="obs.fil",
        backend=backend,
        settings=settings,
    )
    assert status == RunStatus.FAILED
    assert len(result.stages) == 1
    assert result.stages[0].stage == "single_pulse_search"
    assert result.stages[0].status == RunStatus.FAILED
