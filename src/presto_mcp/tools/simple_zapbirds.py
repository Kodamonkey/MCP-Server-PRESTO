"""``presto.simple_zapbirds`` — wrap ``simple_zapbirds.py`` (Fourier birdie zap).

[experimental / image-dependent] ``simple_zapbirds.py`` zaps known interference
("birdies") out of a ``.fft`` **in place**. To honour the no-in-place-mutation
rule, the source ``.fft`` (a prior-run artifact) is copied into the new run's
``artifacts/`` and the zap runs on the *copy* — the source is never touched.

``simple_zapbirds.py`` operates on one ``.fft`` at a time, so this tool takes a
single ``fft_file``; the result fields are lists for forward compatibility.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from ..config import Settings, get_settings
from ..docker_backend import BackendProtocol
from ..errors import DockerInvocationError, PathSecurityError
from ..executor import RunSpec, execute
from ..models import SimpleZapbirdsResult, ToolRunResult
from ..path_security import is_run_artifact_path, resolve_input_path, resolve_run_artifact
from ..runtime_checks import get_tool_readiness

log = logging.getLogger("presto_mcp.tools.simple_zapbirds")


def _check_readiness(backend: BackendProtocol, s: Settings) -> None:
    readiness = get_tool_readiness(backend, s, "simple_zapbirds")
    if not readiness.blocking:
        return
    detail = "; ".join(
        f"{c.name}={c.status}" for c in readiness.checks if c.status != "OK"
    )
    raise DockerInvocationError(
        "Cannot run presto.simple_zapbirds with the configured PRESTO image.\n\n"
        "The MCP tool exists, but the image does not provide the "
        "simple_zapbirds.py routine it wraps.\n\n"
        "Run presto.validate_environment (include_tool_readiness=true) for "
        "details, then use a PRESTO image that ships simple_zapbirds.py.\n\n"
        f"Readiness detail: {detail or 'simple_zapbirds.py unavailable'}"
    )


def run_simple_zapbirds(
    fft_file: str,
    birds_file: str,
    *,
    backend: BackendProtocol,
    settings: Settings | None = None,
    background: bool = False,
) -> ToolRunResult[SimpleZapbirdsResult]:
    """``simple_zapbirds.py <staged>.fft <staged>.birds`` (run on a staged copy)."""
    s = settings or get_settings()
    _check_readiness(backend, s)

    host_fft = resolve_run_artifact(fft_file, s.runs_dir)
    if host_fft.suffix != ".fft":
        raise PathSecurityError(
            f"simple_zapbirds expects a .fft file; got {host_fft.name}"
        )
    fft_name = host_fft.name

    if is_run_artifact_path(birds_file):
        host_birds = resolve_run_artifact(birds_file, s.runs_dir)
    else:
        host_birds = resolve_input_path(birds_file, s.data_dir)
    birds_name = host_birds.name
    if birds_name == fft_name:
        raise PathSecurityError("birds_file and fft_file must have distinct names")

    def hook(run_dir: Path, _extras: tuple[Path, ...]) -> None:
        dst_dir = run_dir / "artifacts"
        dst_dir.mkdir(parents=True, exist_ok=True)
        # Copy the source .fft (+ sibling .inf) — the zap runs on the copy.
        shutil.copy2(host_fft, dst_dir / fft_name)
        inf = host_fft.with_suffix(".inf")
        if inf.exists():
            shutil.copy2(inf, dst_dir / inf.name)
        shutil.copy2(host_birds, dst_dir / birds_name)

    def argv_builder(
        _container_input: str, _extras: tuple[str, ...], _run_dir: Path
    ) -> list[str]:
        return ["simple_zapbirds.py", fft_name, birds_name]

    def parser(stdout: str, run_dir: Path) -> SimpleZapbirdsResult:
        staged = run_dir / "artifacts" / fft_name
        notes: list[str] = []
        zapped = [fft_name] if staged.is_file() else []
        if not zapped:
            notes.append("expected zapped .fft not found in run artifacts")
        return SimpleZapbirdsResult(
            input_fft_files=[fft_file],
            staged_fft_files=[fft_name],
            birds_file=birds_file,
            zapped_fft_files=zapped,
            notes=notes,
        )

    spec = RunSpec[SimpleZapbirdsResult](
        tool_name="simple_zapbirds",
        input_file=None,
        inputs_extra={"fft_file": fft_file, "birds_file": birds_file},
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
