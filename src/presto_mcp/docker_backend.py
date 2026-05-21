"""Docker backend: builds argv lists and runs them via ``subprocess.run``.

The :func:`build_invocation` function is the single source of truth for what a
Docker invocation looks like in this server. Its output is the contract the
golden test pins.

:class:`DockerBackend.run` is the only place ``subprocess.run`` is called for a
PRESTO container. It also owns timeout-kill semantics.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import time
from pathlib import Path
from typing import Protocol

from .errors import DockerInvocationError
from .models import BackendResult, DockerInvocation, RunStatus

from .logging_setup import phase_logger

log = phase_logger("run", "presto_mcp.docker_backend")

CONTAINER_DATA_MOUNT = "/data"
CONTAINER_OUTPUT_MOUNT = "/outputs"
CONTAINER_RUNS_MOUNT = "/runs"
DIAGNOSTIC_EXCERPT_CHARS = 1200


def build_invocation(
    *,
    image: str,
    presto_argv: list[str],
    data_dir: Path,
    run_dir: Path,
    cpus: float,
    memory_mb: int,
    container_name: str,
    docker_bin: str = "docker",
    pids_limit: int = 256,
    network: str = "none",
    stop_timeout_s: int = 5,
    runs_dir_ro: Path | None = None,
    workdir: str | None = None,
) -> DockerInvocation:
    """Construct a :class:`DockerInvocation`. Pure function — no I/O.

    The argv list is fully deterministic given the inputs. Argument order and
    grouping are pinned by the golden test in ``tests/unit/test_docker_backend``.

    When ``runs_dir_ro`` is provided, an additional read-only mount at
    ``/runs`` is appended (used by pipeline tools that consume prior-run
    artifacts).
    """
    if not container_name or " " in container_name:
        raise DockerInvocationError(f"invalid container_name: {container_name!r}")
    if not image:
        raise DockerInvocationError("image must be non-empty")
    if not presto_argv:
        raise DockerInvocationError("presto_argv must be non-empty")

    data_src = str(data_dir.resolve())
    run_src = str(run_dir.resolve())

    argv: list[str] = [
        docker_bin,
        "run",
        "--rm",
        "--name", container_name,
        f"--network={network}",
        f"--cpus={cpus}",
        f"--memory={memory_mb}m",
        f"--pids-limit={pids_limit}",
        "--security-opt", "no-new-privileges",
        f"--stop-timeout={stop_timeout_s}",
        "--mount", f"type=bind,src={data_src},dst={CONTAINER_DATA_MOUNT},readonly",
        "--mount", f"type=bind,src={run_src},dst={CONTAINER_OUTPUT_MOUNT}",
    ]
    if runs_dir_ro is not None:
        runs_src = str(runs_dir_ro.resolve())
        argv += ["--mount", f"type=bind,src={runs_src},dst={CONTAINER_RUNS_MOUNT},readonly"]
    if workdir is not None:
        if not workdir.startswith("/"):
            raise DockerInvocationError(
                f"workdir must be absolute container path, got {workdir!r}"
            )
        argv += ["--workdir", workdir]
    argv += [
        image,
        *presto_argv,
    ]

    return DockerInvocation(
        image=image,
        container_name=container_name,
        argv=argv,
        cpus=cpus,
        memory_mb=memory_mb,
        pids_limit=pids_limit,
        network="none",
    )


class BackendProtocol(Protocol):
    """Interface honored by both ``DockerBackend`` and ``FakeDockerBackend``."""

    def run(
        self, invocation: DockerInvocation, timeout_s: int
    ) -> BackendResult: ...

    def inspect_image_digest(self, image: str) -> str | None: ...


class DockerBackend:
    """Real Docker backend. Uses ``subprocess.run(..., shell=False)`` exclusively."""

    def __init__(self, docker_bin: str | None = None) -> None:
        resolved = docker_bin or shutil.which("docker")
        if not resolved:
            raise DockerInvocationError("docker CLI not found on PATH")
        self.docker_bin = resolved

    def run(self, invocation: DockerInvocation, timeout_s: int) -> BackendResult:
        if invocation.argv[0] != self.docker_bin and invocation.argv[0] != "docker":
            # Builder may have used the literal "docker"; rewrite to absolute path.
            argv = [self.docker_bin, *invocation.argv[1:]]
        else:
            argv = [self.docker_bin, *invocation.argv[1:]]

        log.info("docker start %s", invocation.container_name)

        started = time.monotonic()
        try:
            cp = subprocess.run(
                argv,
                shell=False,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=timeout_s,
                check=False,
            )
        except subprocess.TimeoutExpired as e:
            duration = time.monotonic() - started
            log.warning("timeout after %.1fs; killing %s", duration, invocation.container_name)
            self._kill_container(invocation.container_name)
            return BackendResult(
                status=RunStatus.TIMEOUT,
                exit_code=None,
                stdout=(e.stdout.decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or "")),
                stderr=(e.stderr.decode(errors="replace") if isinstance(e.stderr, bytes) else (e.stderr or "")),
                duration_s=duration,
                error=f"timed out after {timeout_s}s",
            )
        except FileNotFoundError as e:
            raise DockerInvocationError(f"docker binary not found: {e}") from e

        duration = time.monotonic() - started
        status = RunStatus.SUCCESS if cp.returncode == 0 else RunStatus.FAILED
        stdout = cp.stdout or ""
        stderr = cp.stderr or ""
        if status == RunStatus.SUCCESS:
            log.info(
                "docker done %s exit=0 %.1fs",
                invocation.container_name,
                duration,
            )
        else:
            log.warning(
                "docker failed %s exit=%s %.1fs",
                invocation.container_name,
                cp.returncode,
                duration,
            )
        return BackendResult(
            status=status,
            exit_code=cp.returncode,
            stdout=stdout,
            stderr=stderr,
            duration_s=duration,
            error=_failure_error(cp.returncode, stdout, stderr)
            if status == RunStatus.FAILED
            else None,
        )

    def _kill_container(self, name: str) -> None:
        try:
            subprocess.run(
                [self.docker_bin, "kill", name],
                shell=False,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                timeout=10,
                check=False,
            )
        except Exception as e:  # noqa: BLE001
            log.warning("docker kill failed for %s: %s", name, e)

    def inspect_image_digest(self, image: str) -> str | None:
        try:
            cp = subprocess.run(
                [self.docker_bin, "image", "inspect", "--format", "{{index .RepoDigests 0}}", image],
                shell=False,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
        except Exception as e:  # noqa: BLE001
            log.warning("image inspect failed for %s: %s", image, e)
            return None
        if cp.returncode != 0:
            return None
        digest = (cp.stdout or "").strip()
        return digest or None


def _clip(text: str, limit: int = DIAGNOSTIC_EXCERPT_CHARS) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _failure_error(exit_code: int, stdout: str, stderr: str) -> str:
    details = _clip(stderr or stdout)
    label = "docker invocation failed" if exit_code == 125 else "PRESTO command failed"
    if details:
        return f"{label} with exit code {exit_code}: {details}"
    return f"{label} with exit code {exit_code}"
