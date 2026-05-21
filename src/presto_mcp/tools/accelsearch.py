"""``presto.accelsearch`` — Fourier / acceleration candidate search on a ``.fft``.

Like :mod:`realfft`, accelsearch writes its output next to the input. We stage
a copy of the ``.fft`` and the sibling ``.inf`` into the current run's
``artifacts/`` and invoke accelsearch there.

Advanced flags (``-wmax`` jerk search, ``-sigma`` cutoff, ``-ncpus``) are
**capability-aware**: when requested they are checked against ``accelsearch -h``
first. If the configured image's accelsearch does not advertise a flag, the tool
fails fast with a clear error instead of silently dropping it. ``candidate_limit``
only caps the parsed top-N list — it is not passed to PRESTO.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from ..config import Settings, get_settings
from ..docker_backend import BackendProtocol
from ..errors import DockerInvocationError, PathSecurityError
from ..executor import RunSpec, execute
from ..models import AccelsearchResult, ToolRunResult
from ..parsers import accelsearch_parser
from ..path_security import resolve_run_artifact
from ..policies import (
    check_accelsearch_candidate_limit,
    check_accelsearch_ncpus,
    check_accelsearch_sigma,
    check_accelsearch_wmax,
    check_numharm,
    check_zmax,
)
from ..runtime_checks import check_binary_help, check_flag_supported

log = logging.getLogger("presto_mcp.tools.accelsearch")


def run_accelsearch(
    input_file: str,
    *,
    backend: BackendProtocol,
    zmax: int = 200,
    numharm: int = 8,
    wmax: int | None = None,
    sigma: float | None = None,
    ncpus: int | None = None,
    candidate_limit: int | None = None,
    settings: Settings | None = None,
    background: bool = False,
) -> ToolRunResult[AccelsearchResult]:
    """``accelsearch -zmax <z> -numharm <h> [-wmax -sigma -ncpus] <input>.fft``."""
    s = settings or get_settings()
    z = check_zmax(zmax)
    nh = check_numharm(numharm)
    w = check_accelsearch_wmax(wmax)
    sig = check_accelsearch_sigma(sigma)
    nc = check_accelsearch_ncpus(ncpus)
    climit = check_accelsearch_candidate_limit(candidate_limit)

    host_fft = resolve_run_artifact(input_file, s.runs_dir)
    if host_fft.suffix != ".fft":
        raise PathSecurityError(
            f"accelsearch expects a .fft file; got {host_fft.name}"
        )
    name = host_fft.name

    # Capability gate: only probe the image when an advanced flag is requested.
    requested: dict[str, object] = {}
    if w is not None:
        requested["-wmax"] = w
    if sig is not None:
        requested["-sigma"] = sig
    if nc is not None:
        requested["-ncpus"] = nc
    if requested:
        help_check, help_text = check_binary_help(backend, s, "accelsearch")
        if help_check.status == "OK":
            for flag in requested:
                if not check_flag_supported(help_text, flag):
                    raise DockerInvocationError(
                        f"accelsearch in image {s.image} does not support the "
                        f"`{flag}` flag. Omit it, or use a PRESTO image whose "
                        "accelsearch provides it. Run presto.validate_environment "
                        "(include_tool_readiness=true) for capability details."
                    )
        # help_check UNKNOWN -> fail-open: let the real run surface any error.

    def hook(run_dir: Path, _extras: tuple[Path, ...]) -> None:
        dst_dir = run_dir / "artifacts"
        dst_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(host_fft, dst_dir / name)
        inf = host_fft.with_suffix(".inf")
        if inf.exists():
            shutil.copy2(inf, dst_dir / inf.name)

    def argv_builder(
        _container_input: str, _extras: tuple[str, ...], _run_dir: Path
    ) -> list[str]:
        argv = ["accelsearch", "-zmax", str(z), "-numharm", str(nh)]
        if w is not None:
            argv += ["-wmax", str(w)]
        if sig is not None:
            argv += ["-sigma", str(sig)]
        if nc is not None:
            argv += ["-ncpus", str(nc)]
        argv.append(f"/outputs/artifacts/{name}")
        return argv

    def parser(stdout: str, run_dir: Path) -> AccelsearchResult:
        return accelsearch_parser.parse(
            stdout,
            run_dir,
            zmax=z,
            numharm=nh,
            input_fft=name,
            wmax=w,
            sigma=sig,
            ncpus=nc,
            candidate_limit=climit,
        )

    inputs_extra: dict[str, str] = {
        "zmax": str(z),
        "numharm": str(nh),
        "input_fft": input_file,
    }
    if w is not None:
        inputs_extra["wmax"] = str(w)
    if sig is not None:
        inputs_extra["sigma"] = str(sig)
    if nc is not None:
        inputs_extra["ncpus"] = str(nc)

    spec = RunSpec[AccelsearchResult](
        tool_name="accelsearch",
        input_file=None,
        inputs_extra=inputs_extra,
        container_input_path="",
        presto_argv_builder=argv_builder,
        parser=parser,
        timeout_s=s.default_timeout_s,
        cpus=s.default_cpus,
        memory_mb=s.default_memory_mb,
        pre_invocation_hook=hook,
    )
    return execute(spec, s, backend, background=background)
