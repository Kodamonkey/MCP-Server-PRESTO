"""Docker backend: builds argv lists and runs them via ``subprocess.run``.

The :func:`build_invocation` function is the single source of truth for what a
Docker invocation looks like in this server. Its output is the contract the
golden test pins.

:class:`DockerBackend.run` is the only place ``subprocess.run`` is called for a
PRESTO container. It also owns timeout-kill semantics.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Protocol

from .errors import DockerInvocationError
from .models import BackendResult, DockerInvocation, RunStatus

log = logging.getLogger("presto_mcp.docker_backend")

CONTAINER_DATA_MOUNT = "/data"
CONTAINER_OUTPUT_MOUNT = "/outputs"
CONTAINER_RUNS_MOUNT = "/runs"
DIAGNOSTIC_EXCERPT_CHARS = 1200

# How often the resource sampler polls ``docker stats`` while a container runs.
STATS_POLL_INTERVAL_S = 2.0
# Per-poll timeout for the ``docker stats`` call itself.
STATS_CALL_TIMEOUT_S = 5
_STATS_FORMAT = "{{.MemUsage}}|{{.CPUPerc}}"
_MEM_UNIT_TO_MIB = {
    "B": 1.0 / (1024 * 1024),
    "KIB": 1.0 / 1024,
    "KB": 1000.0 / (1024 * 1024),
    "MIB": 1.0,
    "MB": 1000.0 * 1000.0 / (1024 * 1024),
    "GIB": 1024.0,
    "GB": 1000.0 * 1000.0 * 1000.0 / (1024 * 1024),
    "TIB": 1024.0 * 1024.0,
}


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
    mount_data: bool = True,
) -> DockerInvocation:
    """Construct a :class:`DockerInvocation`. Pure function — no I/O.

    The argv list is fully deterministic given the inputs. Argument order and
    grouping are pinned by the golden test in ``tests/unit/test_docker_backend``.

    When ``runs_dir_ro`` is provided, an additional read-only mount at
    ``/runs`` is appended (used by pipeline tools that consume prior-run
    artifacts).

    When ``mount_data`` is ``False``, the ``/data`` bind mount is skipped
    (pure-compute tools like ``DDplan.py`` need no observation input). The
    executor decides this based on whether any input or extra_input has
    ``root="data"``.
    """
    if not container_name or " " in container_name:
        raise DockerInvocationError(f"invalid container_name: {container_name!r}")
    if not image:
        raise DockerInvocationError("image must be non-empty")
    if not presto_argv:
        raise DockerInvocationError("presto_argv must be non-empty")

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
    ]
    if mount_data:
        data_src = str(data_dir.resolve())
        argv += [
            "--mount", f"type=bind,src={data_src},dst={CONTAINER_DATA_MOUNT},readonly",
        ]
    argv += [
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


def _parse_mem_to_mib(raw: str) -> float | None:
    """Convert a docker-stats memory token (e.g. ``"123.4MiB"``) to MiB.

    Returns ``None`` for unparseable / placeholder (``--``) tokens.
    """
    raw = raw.strip()
    if not raw or raw == "--":
        return None
    m = re.match(r"^([0-9]*\.?[0-9]+)\s*([A-Za-z]+)$", raw)
    if not m:
        return None
    factor = _MEM_UNIT_TO_MIB.get(m.group(2).upper())
    if factor is None:
        return None
    return float(m.group(1)) * factor


def _parse_cpu_perc(raw: str) -> float | None:
    """Parse a docker-stats CPU token (e.g. ``"45.20%"``) to a float percent."""
    raw = raw.strip().rstrip("%").strip()
    if not raw or raw == "--":
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def parse_stats_line(line: str) -> tuple[float | None, float | None]:
    """Parse one ``MemUsage|CPUPerc`` stats line → ``(mem_used_mib, cpu_percent)``.

    ``MemUsage`` arrives as ``"<used> / <limit>"``; only the used side is taken.
    """
    if "|" not in line:
        return None, None
    mem_part, _, cpu_part = line.partition("|")
    mem_used = mem_part.split("/")[0]
    return _parse_mem_to_mib(mem_used), _parse_cpu_perc(cpu_part)


class _ResourceSampler:
    """Polls ``docker stats`` for one container in a daemon thread.

    Best-effort: every failure is swallowed so sampling can never break a run.
    ``summary()`` returns the metrics accumulated so far (zero samples when
    stats were never available — e.g. a container that exits faster than one
    poll interval, which keeps fast unit tests free of stats subprocess calls).
    """

    def __init__(
        self,
        docker_bin: str,
        container_name: str,
        interval_s: float = STATS_POLL_INTERVAL_S,
    ) -> None:
        self._docker_bin = docker_bin
        self._name = container_name
        self._interval = interval_s
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._peak_mem_mib: float | None = None
        self._cpu_samples: list[float] = []
        self._samples = 0

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._loop, name=f"stats-{self._name}", daemon=True
        )
        self._thread.start()

    def _loop(self) -> None:
        # wait() returns True once stopped; waiting *before* the first poll means
        # a container finishing within one interval yields zero samples.
        while not self._stop.wait(self._interval):
            self._sample_once()

    def _sample_once(self) -> None:
        try:
            cp = subprocess.run(
                [
                    self._docker_bin, "stats", "--no-stream",
                    "--format", _STATS_FORMAT, self._name,
                ],
                shell=False,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=STATS_CALL_TIMEOUT_S,
                check=False,
            )
        except Exception:  # noqa: BLE001 - sampling must never break a run
            return
        if cp.returncode != 0:
            return
        mem_mib, cpu = parse_stats_line((cp.stdout or "").strip())
        if mem_mib is not None:
            self._peak_mem_mib = (
                mem_mib if self._peak_mem_mib is None else max(self._peak_mem_mib, mem_mib)
            )
        if cpu is not None:
            self._cpu_samples.append(cpu)
        if mem_mib is not None or cpu is not None:
            self._samples += 1

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=STATS_CALL_TIMEOUT_S + 1)
            self._thread = None

    def summary(self) -> dict[str, float | int | None]:
        """Metrics dict whose keys match the ``BackendResult`` metric fields."""
        cpu_peak = max(self._cpu_samples) if self._cpu_samples else None
        cpu_avg = (
            sum(self._cpu_samples) / len(self._cpu_samples) if self._cpu_samples else None
        )
        return {
            "peak_memory_mb": round(self._peak_mem_mib, 1) if self._peak_mem_mib is not None else None,
            "cpu_percent_peak": round(cpu_peak, 2) if cpu_peak is not None else None,
            "cpu_percent_avg": round(cpu_avg, 2) if cpu_avg is not None else None,
            "resource_samples": self._samples,
        }


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

        sampler = _ResourceSampler(self.docker_bin, invocation.container_name)
        sampler.start()
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
            sampler.stop()
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
                **sampler.summary(),
            )
        except FileNotFoundError as e:
            sampler.stop()
            raise DockerInvocationError(f"docker binary not found: {e}") from e
        finally:
            sampler.stop()

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
            **sampler.summary(),
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
