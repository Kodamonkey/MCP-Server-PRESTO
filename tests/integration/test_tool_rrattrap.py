"""Integration test for rrattrap with FakeDockerBackend."""

from __future__ import annotations

from pathlib import Path

import pytest

from presto_mcp.config import Settings
from presto_mcp.errors import DockerInvocationError, PathSecurityError, PolicyViolationError
from presto_mcp.manifest import load_manifest
from presto_mcp.models import RunStatus
from presto_mcp.tools.rrattrap import run_rrattrap
from tests.fakes.fake_docker_backend import FakeDockerBackend, FakeResponse

PRIOR_RUN_ID = "20260517T120000Z-RRRRRR"

_GROUPS = """\
Group 1 ...
Group 2 ...
Group 3 ...
"""


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    data = tmp_path / "data"
    data.mkdir()
    runs = tmp_path / "runs"
    prior = runs / PRIOR_RUN_ID / "artifacts"
    prior.mkdir(parents=True)
    for dm in ("0.00", "0.10"):
        (prior / f"sub_DM{dm}.singlepulse").write_bytes(b"# x\n1 2 3 4 5\n")
    (prior / "sub.inf").write_bytes(b"hdr")
    return Settings(
        image="alex88ridolfi/presto5:png",
        data_dir=data.resolve(),
        runs_dir=runs.resolve(),
        outputs_dir=(tmp_path / "outputs").resolve(),
        logs_dir=(tmp_path / "logs").resolve(),
        default_cpus=2.0, default_memory_mb=1024, default_timeout_s=60,
        network="none", skip_healthcheck=True,
    )


def _post_image(call: object) -> tuple[str, ...]:
    """argv elements after the image — the PRESTO/probe command itself."""
    argv = call.invocation.argv  # type: ignore[attr-defined]
    image = call.invocation.image  # type: ignore[attr-defined]
    idx = argv.index(image)
    return tuple(argv[idx + 1 :])


def test_rrattrap_argv_workdir_and_groups(settings: Settings) -> None:
    backend = FakeDockerBackend(
        responses={
            "rrattrap.py": FakeResponse(
                stdout="grouped\n",
                status=RunStatus.SUCCESS,
                artifacts={"groups.txt": _GROUPS.encode("utf-8")},
            )
        },
        probe_responses={
            "which:rrattrap.py": FakeResponse(status=RunStatus.SUCCESS),
            "module:presto.singlepulse": FakeResponse(status=RunStatus.SUCCESS),
        },
    )
    result = run_rrattrap(
        [
            f"{PRIOR_RUN_ID}/artifacts/sub_DM0.00.singlepulse",
            f"{PRIOR_RUN_ID}/artifacts/sub_DM0.10.singlepulse",
        ],
        f"{PRIOR_RUN_ID}/artifacts/sub.inf",
        backend=backend, settings=settings, min_group=2,
    )
    assert result.status == RunStatus.SUCCESS
    assert result.result is not None
    assert result.result.groups_file == "groups.txt"
    assert result.result.num_groups == 3

    # readiness preflight probes rrattrap.py + presto.singlepulse, then the run.
    rrattrap_calls = [c for c in backend.calls if _post_image(c)[0] == "rrattrap.py"]
    assert len(rrattrap_calls) == 1
    probe_cmds = {_post_image(c)[0] for c in backend.calls}
    assert "which" in probe_cmds and "python3" in probe_cmds

    argv = rrattrap_calls[0].invocation.argv
    assert "rrattrap.py" in argv
    assert "--inffile" in argv and "sub.inf" in argv
    assert "--min-group" in argv and "2" in argv
    assert "sub_DM0.00.singlepulse" in argv
    assert "sub_DM0.10.singlepulse" in argv
    assert "--workdir" in argv
    assert "/outputs/artifacts" in argv

    run_dir = settings.runs_dir / result.run_id
    assert (run_dir / "artifacts" / "sub_DM0.00.singlepulse").is_file()
    assert (run_dir / "artifacts" / "sub.inf").is_file()

    m = load_manifest(run_dir)
    assert m.tool == "rrattrap"


def test_rrattrap_rejects_empty(settings: Settings) -> None:
    backend = FakeDockerBackend(
        responses={"python3": FakeResponse(stdout="", status=RunStatus.SUCCESS)}
    )
    with pytest.raises(PolicyViolationError):
        run_rrattrap(
            [], f"{PRIOR_RUN_ID}/artifacts/sub.inf",
            backend=backend, settings=settings,
        )


def test_rrattrap_rejects_non_singlepulse(settings: Settings) -> None:
    backend = FakeDockerBackend(
        responses={"python3": FakeResponse(stdout="", status=RunStatus.SUCCESS)}
    )
    with pytest.raises(PathSecurityError):
        run_rrattrap(
            [f"{PRIOR_RUN_ID}/artifacts/sub.inf"],
            f"{PRIOR_RUN_ID}/artifacts/sub.inf",
            backend=backend, settings=settings,
        )


def test_rrattrap_preflight_fails_with_controlled_error(settings: Settings) -> None:
    backend = FakeDockerBackend(
        probe_responses={
            "which:rrattrap.py": FakeResponse(status=RunStatus.SUCCESS),
            "module:presto.singlepulse": FakeResponse(
                stdout="",
                stderr="ModuleNotFoundError: No module named 'presto.singlepulse'",
                status=RunStatus.FAILED,
                exit_code=1,
            ),
        }
    )
    with pytest.raises(DockerInvocationError, match="Cannot run presto\\.rrattrap") as ei:
        run_rrattrap(
            [f"{PRIOR_RUN_ID}/artifacts/sub_DM0.00.singlepulse"],
            f"{PRIOR_RUN_ID}/artifacts/sub.inf",
            backend=backend, settings=settings,
        )
    msg = str(ei.value)
    # the controlled error must name the script, the module and the diagnostic tool
    assert "rrattrap.py" in msg
    assert "presto.singlepulse" in msg
    assert "validate_environment" in msg
    # the executor must NOT have been reached: no rrattrap.py invocation
    assert not any(
        c.invocation.argv[c.invocation.argv.index(c.invocation.image) + 1]
        == "rrattrap.py"
        for c in backend.calls
    )
