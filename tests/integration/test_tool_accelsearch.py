"""Integration test for accelsearch with FakeDockerBackend."""

from __future__ import annotations

from pathlib import Path

import pytest

from presto_mcp.config import Settings
from presto_mcp.errors import (
    DockerInvocationError,
    PathSecurityError,
    PolicyViolationError,
)
from presto_mcp.manifest import load_manifest
from presto_mcp.models import RunStatus
from presto_mcp.tools.accelsearch import run_accelsearch
from tests.fakes.fake_docker_backend import FakeDockerBackend, FakeResponse

_HELP_WITH_ADVANCED = (
    "Usage: accelsearch [-zmax z] [-numharm h] [-wmax w] [-sigma s] [-ncpus n]"
)
_HELP_BASIC = "Usage: accelsearch [-zmax z] [-numharm h]"

PRIOR_RUN_ID = "20260517T120000Z-BBBBBB"

_TXTCAND = """\
#  Cand   Sigma   Power   Freq      FFTReal   Z        Period(ms)
   1      11.2    150.0   100.0     50.0      2.0      10.0
"""


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    data = tmp_path / "data"
    data.mkdir()
    runs = tmp_path / "runs"
    prior = runs / PRIOR_RUN_ID / "artifacts"
    prior.mkdir(parents=True)
    (prior / "prep.fft").write_bytes(b"F")
    (prior / "prep.inf").write_bytes(b"i")
    return Settings(
        image="alex88ridolfi/presto5:png",
        data_dir=data.resolve(),
        runs_dir=runs.resolve(),
        outputs_dir=(tmp_path / "outputs").resolve(),
        logs_dir=(tmp_path / "logs").resolve(),
        default_cpus=2.0, default_memory_mb=1024, default_timeout_s=60,
        network="none", skip_healthcheck=True,
    )


def test_accelsearch_argv_and_top_candidates(settings: Settings) -> None:
    backend = FakeDockerBackend(
        responses={
            "accelsearch": FakeResponse(
                stdout="searching...\n",
                status=RunStatus.SUCCESS,
                artifacts={
                    "prep_ACCEL_200": b"X",
                    "prep_ACCEL_200.txtcand": _TXTCAND.encode("utf-8"),
                },
            )
        }
    )
    result = run_accelsearch(
        f"{PRIOR_RUN_ID}/artifacts/prep.fft",
        backend=backend, zmax=200, numharm=8, settings=settings,
    )
    assert result.status == RunStatus.SUCCESS
    assert result.result is not None
    assert result.result.zmax == 200
    assert result.result.numharm == 8
    assert result.result.accel_txtcand_file == "prep_ACCEL_200.txtcand"
    assert len(result.result.top_candidates) == 1
    assert result.result.top_candidates[0].sigma == 11.2

    argv = backend.calls[0].invocation.argv
    assert "accelsearch" in argv
    assert "-zmax" in argv and "200" in argv
    assert "-numharm" in argv and "8" in argv
    assert "/outputs/artifacts/prep.fft" in argv

    m = load_manifest(settings.runs_dir / result.run_id)
    assert m.tool == "accelsearch"


@pytest.mark.parametrize("nh", [3, 0, 64])
def test_accelsearch_rejects_bad_numharm(settings: Settings, nh: int) -> None:
    backend = FakeDockerBackend()
    with pytest.raises(PolicyViolationError):
        run_accelsearch(
            f"{PRIOR_RUN_ID}/artifacts/prep.fft",
            backend=backend, zmax=200, numharm=nh, settings=settings,
        )


def test_accelsearch_rejects_non_fft(settings: Settings) -> None:
    prior_dir = settings.runs_dir / PRIOR_RUN_ID / "artifacts"
    (prior_dir / "prep.dat").write_bytes(b"D")
    backend = FakeDockerBackend()
    with pytest.raises(PathSecurityError, match=".fft"):
        run_accelsearch(
            f"{PRIOR_RUN_ID}/artifacts/prep.dat",
            backend=backend, settings=settings,
        )


def test_accelsearch_advanced_flags_when_supported(settings: Settings) -> None:
    backend = FakeDockerBackend(
        responses={
            "accelsearch": FakeResponse(
                stdout="searching...\n",
                status=RunStatus.SUCCESS,
                artifacts={"prep_ACCEL_200": b"X"},
            )
        },
        probe_responses={
            "help:accelsearch": FakeResponse(
                status=RunStatus.SUCCESS, stdout=_HELP_WITH_ADVANCED
            )
        },
    )
    result = run_accelsearch(
        f"{PRIOR_RUN_ID}/artifacts/prep.fft",
        backend=backend, zmax=200, numharm=8,
        wmax=50, sigma=3.0, ncpus=2, settings=settings,
    )
    assert result.status == RunStatus.SUCCESS
    run_call = next(
        c for c in backend.calls
        if "accelsearch" in c.invocation.argv and "-h" not in c.invocation.argv
    )
    argv = run_call.invocation.argv
    assert "-wmax" in argv and "50" in argv
    assert "-sigma" in argv and "3.0" in argv
    assert "-ncpus" in argv and "2" in argv
    assert result.result is not None
    assert result.result.wmax == 50


def test_accelsearch_wmax_rejected_when_unsupported(settings: Settings) -> None:
    backend = FakeDockerBackend(
        probe_responses={
            "help:accelsearch": FakeResponse(
                status=RunStatus.SUCCESS, stdout=_HELP_BASIC
            )
        },
    )
    with pytest.raises(DockerInvocationError, match="-wmax"):
        run_accelsearch(
            f"{PRIOR_RUN_ID}/artifacts/prep.fft",
            backend=backend, wmax=50, settings=settings,
        )


def test_accelsearch_no_help_probe_without_advanced_flags(settings: Settings) -> None:
    backend = FakeDockerBackend(
        responses={
            "accelsearch": FakeResponse(stdout="ok\n", status=RunStatus.SUCCESS)
        }
    )
    run_accelsearch(
        f"{PRIOR_RUN_ID}/artifacts/prep.fft",
        backend=backend, zmax=200, numharm=8, settings=settings,
    )
    # no advanced flags -> no `accelsearch -h` capability probe
    assert all("-h" not in c.invocation.argv for c in backend.calls)


@pytest.mark.parametrize("bad", [-1, 9999])
def test_accelsearch_rejects_bad_wmax(settings: Settings, bad: int) -> None:
    backend = FakeDockerBackend()
    with pytest.raises(PolicyViolationError):
        run_accelsearch(
            f"{PRIOR_RUN_ID}/artifacts/prep.fft",
            backend=backend, wmax=bad, settings=settings,
        )
