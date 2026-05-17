"""``presto.get_toas`` — wrap ``get_TOAs.py`` (TOA generation from a ``.pfd``).

Takes a folded profile ``.pfd`` (output of ``prepfold`` in a prior run) plus
a Gaussian template (``.gaussians`` / ``.template``) under ``DATA_DIR``.
Prints TEMPO/TEMPO2 TOA lines on stdout.

Pipeline-chained: the ``.pfd`` is read read-only via the ``/runs`` mount; the
template is read from ``/data``.
"""

from __future__ import annotations

import logging
from pathlib import Path

from ..config import Settings, get_settings
from ..docker_backend import BackendProtocol
from ..executor import ExtraInput, RunSpec, execute
from ..models import GetTOAsResult, ToolRunResult
from ..parsers import get_toas_parser
from ..policies import check_toas_subbands, check_toas_subints

log = logging.getLogger("presto_mcp.tools.get_toas")


def run_get_toas(
    pfd_file: str,
    template_file: str,
    *,
    backend: BackendProtocol,
    num_subints: int = 1,
    num_subbands: int = 1,
    settings: Settings | None = None,
    background: bool = False,
) -> ToolRunResult[GetTOAsResult]:
    """``get_TOAs.py -g <template> -s <subints> -n <subbands> <pfd>``.

    ``pfd_file`` is interpreted as ``<run_id>/artifacts/<file>.pfd`` relative
    to ``RUNS_DIR``. ``template_file`` is interpreted relative to ``DATA_DIR``.
    """
    s = settings or get_settings()
    nsub = check_toas_subints(num_subints)
    nband = check_toas_subbands(num_subbands)

    extras = (ExtraInput(path=template_file, root="data"),)

    def argv_builder(
        container_input: str, extra_paths: tuple[str, ...], _run_dir: Path
    ) -> list[str]:
        template_container = extra_paths[0]
        return [
            "get_TOAs.py",
            "-g", template_container,
            "-s", str(nsub),
            "-n", str(nband),
            container_input,
        ]

    def parser(stdout: str, run_dir: Path) -> GetTOAsResult:
        return get_toas_parser.parse(
            stdout,
            run_dir,
            pfd_file=pfd_file,
            template_file=template_file,
            num_subints=nsub,
            num_subbands=nband,
        )

    spec = RunSpec[GetTOAsResult](
        tool_name="get_toas",
        input_file=pfd_file,
        inputs_extra={
            "pfd_file": pfd_file,
            "template_file": template_file,
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
