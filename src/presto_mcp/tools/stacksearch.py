"""``presto.stacksearch`` — wrap ``stacksearch.py`` (stack search over ``.fft``).

[experimental / image-dependent] Stack-searches several ``.fft`` files (each
from a prior realfft run) to boost weak periodic signals. ``stacksearch.py`` is
not present in every PRESTO image — a readiness preflight fails fast with a
controlled error rather than a confusing traceback.

Inputs are ``<run_id>/artifacts/<file>.fft`` relative to RUNS_DIR. Each ``.fft``
(plus its sibling ``.inf``) is staged into the new run's ``artifacts/`` and the
search runs there; the source files are never modified.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from ..config import Settings, get_settings
from ..docker_backend import BackendProtocol
from ..errors import DockerInvocationError, PathSecurityError
from ..executor import RunSpec, execute
from ..models import StackSearchResult, ToolRunResult
from ..parsers import stacksearch_parser
from ..path_security import resolve_run_artifact
from ..policies import check_stacksearch_input_count
from ..runtime_checks import get_tool_readiness

log = logging.getLogger("presto_mcp.tools.stacksearch")


def _check_readiness(backend: BackendProtocol, s: Settings) -> None:
    readiness = get_tool_readiness(backend, s, "stacksearch")
    if not readiness.blocking:
        return
    detail = "; ".join(
        f"{c.name}={c.status}" for c in readiness.checks if c.status != "OK"
    )
    raise DockerInvocationError(
        "Cannot run presto.stacksearch with the configured PRESTO image.\n\n"
        "The MCP tool presto.stacksearch exists, but the image does not provide "
        "the stacksearch.py routine it wraps.\n\n"
        "This is a PRESTO Docker image issue, not an MCP tool issue.\n"
        "Run presto.validate_environment (include_tool_readiness=true) for the "
        "full report, then use a PRESTO image that ships stacksearch.py.\n\n"
        f"Readiness detail: {detail or 'stacksearch.py unavailable'}"
    )


def run_stacksearch(
    fft_files: list[str],
    *,
    backend: BackendProtocol,
    settings: Settings | None = None,
    background: bool = False,
) -> ToolRunResult[StackSearchResult]:
    """``stacksearch.py <file1>.fft <file2>.fft ...`` (run in artifacts/)."""
    s = settings or get_settings()
    _check_readiness(backend, s)
    check_stacksearch_input_count(len(fft_files))

    host_fft: list[Path] = []
    names: list[str] = []
    for rel in fft_files:
        host = resolve_run_artifact(rel, s.runs_dir)
        if host.suffix != ".fft":
            raise PathSecurityError(
                f"stacksearch expects .fft files; got {host.name}"
            )
        host_fft.append(host)
        names.append(host.name)

    if len(set(names)) != len(names):
        raise PathSecurityError(
            "stacksearch inputs must have unique filenames after staging"
        )

    def hook(run_dir: Path, _extras: tuple[Path, ...]) -> None:
        dst_dir = run_dir / "artifacts"
        dst_dir.mkdir(parents=True, exist_ok=True)
        for host in host_fft:
            shutil.copy2(host, dst_dir / host.name)
            inf = host.with_suffix(".inf")
            if inf.exists():
                shutil.copy2(inf, dst_dir / inf.name)

    def argv_builder(
        _container_input: str, _extras: tuple[str, ...], _run_dir: Path
    ) -> list[str]:
        return ["stacksearch.py", *names]

    def parser(stdout: str, run_dir: Path) -> StackSearchResult:
        return stacksearch_parser.parse(
            stdout,
            run_dir,
            fft_files=tuple(fft_files),
            staged_names=tuple(names),
        )

    spec = RunSpec[StackSearchResult](
        tool_name="stacksearch",
        input_file=None,
        inputs_extra={"fft_count": str(len(fft_files))},
        container_input_path="",
        presto_argv_builder=argv_builder,
        parser=parser,
        timeout_s=s.default_timeout_s,
        cpus=s.default_cpus,
        memory_mb=s.default_memory_mb,
        pre_invocation_hook=hook,
        container_workdir="/outputs/artifacts",
    )
    return execute(spec, s, backend, background=background)
