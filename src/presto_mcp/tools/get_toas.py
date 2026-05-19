"""``presto.get_toas`` — wrap ``get_TOAs.py`` (TOA generation from a ``.pfd``).

Takes a folded profile ``.pfd`` (output of ``prepfold`` in a prior run) plus
a template source: either a Gaussian template file under ``DATA_DIR`` or a
numeric Gaussian FWHM width accepted by PRESTO's ``-g`` flag. Prints
TEMPO/TEMPO2 TOA lines on stdout.

Pipeline-chained: the ``.pfd`` is read read-only via the ``/runs`` mount; an
optional template file is read from ``/data``.
"""

from __future__ import annotations

import logging
from pathlib import Path

from ..config import Settings, get_settings
from ..docker_backend import BackendProtocol
from ..errors import PolicyViolationError
from ..executor import ExtraInput, RunSpec, execute
from ..models import GetTOAsResult, ToolRunResult
from ..parsers import get_toas_parser
from ..policies import check_toas_gaussian_width, check_toas_subbands, check_toas_subints

log = logging.getLogger("presto_mcp.tools.get_toas")


def run_get_toas(
    pfd_file: str,
    template_file: str | None = None,
    *,
    backend: BackendProtocol,
    num_subints: int = 1,
    num_subbands: int = 1,
    gaussian_width: float | None = None,
    settings: Settings | None = None,
    background: bool = False,
) -> ToolRunResult[GetTOAsResult]:
    """``get_TOAs.py -g <template-or-width> -n <subints> -s <subbands> <pfd>``.

    ``pfd_file`` is interpreted as ``<run_id>/artifacts/<file>.pfd`` relative
    to ``RUNS_DIR``. ``template_file`` is interpreted relative to ``DATA_DIR``.
    If no template file is available, ``gaussian_width`` supplies PRESTO's
    numeric Gaussian FWHM width directly.
    """
    s = settings or get_settings()
    nsub = check_toas_subints(num_subints)
    nband = check_toas_subbands(num_subbands)
    width = check_toas_gaussian_width(gaussian_width)

    if (template_file is None) == (width is None):
        raise PolicyViolationError(
            "get_toas requires exactly one of template_file or gaussian_width"
        )

    extras = (ExtraInput(path=template_file, root="data"),) if template_file else ()
    template_label = template_file if template_file is not None else f"gaussian_width={width}"

    def argv_builder(
        container_input: str, extra_paths: tuple[str, ...], _run_dir: Path
    ) -> list[str]:
        template_arg = extra_paths[0] if template_file else str(width)
        return [
            "get_TOAs.py",
            "-g", template_arg,
            "-n", str(nsub),
            "-s", str(nband),
            container_input,
        ]

    def parser(stdout: str, run_dir: Path) -> GetTOAsResult:
        return get_toas_parser.parse(
            stdout,
            run_dir,
            pfd_file=pfd_file,
            template_file=template_label,
            num_subints=nsub,
            num_subbands=nband,
        )

    spec = RunSpec[GetTOAsResult](
        tool_name="get_toas",
        input_file=pfd_file,
        inputs_extra={
            "pfd_file": pfd_file,
            "template_file": template_label,
            "num_subints": str(nsub),
            "num_subbands": str(nband),
        },
        container_input_path="",
        presto_argv_builder=argv_builder,
        parser=parser,
        timeout_s=s.default_timeout_s,
        cpus=s.default_cpus,
        memory_mb=s.default_memory_mb,
        input_root="runs",
        extra_inputs=extras,
    )
    return execute(spec, s, backend, background=background)
