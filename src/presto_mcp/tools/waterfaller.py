"""``presto.waterfaller`` — wrap ``waterfaller.py`` (dynamic-spectrum plot).

Renders a waterfall (dynamic spectrum) around a candidate ``(start_s,
duration_s, dm)`` for a raw filterbank / PSRFITS file (under ``DATA_DIR``).
Optionally accepts an rfifind ``.mask`` (under ``DATA_DIR``).

Upstream ``waterfaller.py`` only calls ``plt.show()``; we stage
``waterfaller_headless.py`` into the run dir so matplotlib saves
``waterfall.png`` under ``/outputs/artifacts``.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from ..config import Settings, get_settings
from ..docker_backend import BackendProtocol
from ..executor import ExtraInput, RunSpec, execute, extra_input_for
from ..models import ToolRunResult, WaterfallerResult
from ..parsers import waterfaller_parser
from ..path_security import is_run_artifact_path
from ..policies import check_dm, check_waterfall_duration, check_waterfall_start

log = logging.getLogger("presto_mcp.tools.waterfaller")

_HEADLESS_SCRIPT = Path(__file__).resolve().parent.parent / "bin" / "waterfaller_headless.py"
_CONTAINER_WRAPPER = "/outputs/artifacts/waterfaller_headless.py"


def _stage_headless_wrapper(run_dir: Path, _extras: tuple[Path, ...]) -> None:
    dest = run_dir / "artifacts" / "waterfaller_headless.py"
    shutil.copy(_HEADLESS_SCRIPT, dest)


def run_waterfaller(
    input_file: str,
    *,
    backend: BackendProtocol,
    start_s: float,
    duration_s: float,
    dm: float,
    mask_file: str | None = None,
    colour_map: str | None = None,
    nsub: int | None = None,
    nbins: int | None = None,
    downsamp: int | None = None,
    settings: Settings | None = None,
    background: bool = False,
) -> ToolRunResult[WaterfallerResult]:
    """``waterfaller.py -T <t0> -t <dur> -d <dm> [--mask --maskfile <m>] <raw>``.

    ``input_file`` may be either relative to ``DATA_DIR`` or
    ``<run_id>/artifacts/<file>`` from a prior run (e.g. a ``.fil`` produced by
    ``psrfits2fil``, ``fb_truncate``, or ``downsample_filterbank``); the root is
    auto-detected from the path shape. Optional ``mask_file`` follows the same
    auto-detection.
    """
    s = settings or get_settings()
    t0 = check_waterfall_start(start_s)
    dur = check_waterfall_duration(duration_s)
    d = check_dm(dm)

    extras_list: list[ExtraInput] = []
    if mask_file is not None:
        extras_list.append(extra_input_for(mask_file))
    extras = tuple(extras_list)
    container_python = s.resolved_python_bin()
    cmap = (colour_map or "").strip() or None

    def argv_builder(
        container_input: str, extra_paths: tuple[str, ...], _run_dir: Path
    ) -> list[str]:
        argv = [
            container_python,
            _CONTAINER_WRAPPER,
            "-T", str(t0),
            "-t", str(dur),
            "-d", str(d),
        ]
        if nsub is not None:
            argv += ["-s", str(int(nsub))]
        if nbins is not None:
            argv += ["-n", str(int(nbins))]
        if downsamp is not None:
            argv += ["--downsamp", str(int(downsamp))]
        if mask_file is not None:
            argv += ["--mask", "--maskfile", extra_paths[0]]
        if cmap is not None:
            argv += ["--colour-map", cmap]
        argv.append(container_input)
        return argv

    def parser(stdout: str, run_dir: Path) -> WaterfallerResult:
        return waterfaller_parser.parse(
            stdout,
            run_dir,
            input_raw=input_file,
            start_s=t0,
            duration_s=dur,
            dm=d,
            mask_file=mask_file,
        )

    inputs_extra: dict[str, str] = {
        "start_s": str(t0),
        "duration_s": str(dur),
        "dm": str(d),
    }
    if mask_file is not None:
        inputs_extra["mask_file"] = mask_file
    if cmap is not None:
        inputs_extra["colour_map"] = cmap
    if nsub is not None:
        inputs_extra["nsub"] = str(int(nsub))
    if nbins is not None:
        inputs_extra["nbins"] = str(int(nbins))
    if downsamp is not None:
        inputs_extra["downsamp"] = str(int(downsamp))

    input_root = "runs" if is_run_artifact_path(input_file) else "data"
    spec = RunSpec[WaterfallerResult](
        tool_name="waterfaller",
        input_file=input_file,
        inputs_extra=inputs_extra,
        container_input_path="",
        presto_argv_builder=argv_builder,
        parser=parser,
        timeout_s=s.default_timeout_s,
        cpus=s.default_cpus,
        memory_mb=s.default_memory_mb,
        input_root=input_root,
        extra_inputs=extras,
        container_workdir="/outputs/artifacts",
        pre_invocation_hook=_stage_headless_wrapper,
    )
    return execute(spec, s, backend, background=background)
