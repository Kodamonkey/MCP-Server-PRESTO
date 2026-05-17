"""``presto.zapbirds`` — wrap ``zapbirds`` (apply a zaplist to a ``.fft``).

``zapbirds`` rewrites the input ``.fft`` in place. The input lives in a prior
run's ``artifacts/`` (mounted read-only at ``/runs``), so we stage a copy of
the ``.fft`` and its sibling ``.inf`` into the current run's ``artifacts/``
and invoke ``zapbirds`` against ``/outputs/artifacts/<name>.fft``.

The zaplist is interpreted relative to ``DATA_DIR`` (user-curated birds /
zap file).
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from ..config import Settings, get_settings
from ..docker_backend import BackendProtocol
from ..errors import PathSecurityError
from ..executor import ExtraInput, RunSpec, execute
from ..models import ToolRunResult, ZapbirdsResult
from ..parsers import zapbirds_parser
from ..path_security import resolve_run_artifact
from ..policies import check_zapbirds_baryv, check_zapbirds_nfft

log = logging.getLogger("presto_mcp.tools.zapbirds")


def run_zapbirds(
    input_fft: str,
    zaplist_file: str,
    *,
    backend: BackendProtocol,
    baryv: float | None = None,
    nfft: int | None = None,
    settings: Settings | None = None,
    background: bool = False,
) -> ToolRunResult[ZapbirdsResult]:
    """``zapbirds -zap -zaplist <zaplist> /outputs/artifacts/<input>.fft``.

    ``input_fft`` is ``<run_id>/artifacts/<file>.fft`` relative to ``RUNS_DIR``.
    ``zaplist_file`` is relative to ``DATA_DIR``.
    """
    s = settings or get_settings()
    bv = check_zapbirds_baryv(baryv)
    nf = check_zapbirds_nfft(nfft)

    host_fft = resolve_run_artifact(input_fft, s.runs_dir)
    if host_fft.suffix != ".fft":
        raise PathSecurityError(
            f"zapbirds expects a .fft file; got {host_fft.name}"
        )
    name = host_fft.name

    extras = (ExtraInput(path=zaplist_file, root="data"),)

    def hook(run_dir: Path, _extras: tuple[Path, ...]) -> None:
        dst_dir = run_dir / "artifacts"
        dst_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(host_fft, dst_dir / name)
        inf = host_fft.with_suffix(".inf")
        if inf.exists():
            shutil.copy2(inf, dst_dir / inf.name)

    def argv_builder(
        _container_input: str, extra_paths: tuple[str, ...], _run_dir: Path
    ) -> list[str]:
        zap_container = extra_paths[0]
        argv = [
            "zapbirds",
            "-zap",
            "-zaplist", zap_container,
        ]
        if bv is not None:
            argv += ["-baryv", str(bv)]
        if nf is not None:
            argv += ["-N", str(nf)]
        argv.append(f"/outputs/artifacts/{name}")
        return argv

    def parser(stdout: str, run_dir: Path) -> ZapbirdsResult:
        return zapbirds_parser.parse(
            stdout,
            run_dir,
            input_fft=input_fft,
            zaplist_file=zaplist_file,
        )

    inputs_extra: dict[str, str] = {
        "input_fft": input_fft,
        "zaplist_file": zaplist_file,
    }
    if bv is not None:
        inputs_extra["baryv"] = str(bv)
    if nf is not None:
        inputs_extra["nfft"] = str(nf)

    spec = RunSpec[ZapbirdsResult](
        tool_name="zapbirds",
        input_file=None,
        inputs_extra=inputs_extra,
        container_input_path="",
        presto_argv_builder=argv_builder,
        parser=parser,
        timeout_s=s.default_timeout_s,
        cpus=s.default_cpus,
        memory_mb=s.default_memory_mb,
        extra_inputs=extras,
        pre_invocation_hook=hook,
    )
    return execute(spec, s, backend, background=background)
