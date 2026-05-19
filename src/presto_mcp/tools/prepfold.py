"""``presto.prepfold`` — Mode A only (input + period + DM).

The richer "candidate file" Mode B is documented in the README as a future
phase. This module intentionally exposes only what the MVP can validate end-to-end.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from ..config import Settings, get_settings
from ..docker_backend import BackendProtocol
from ..executor import RunSpec, execute
from ..models import PrepfoldResult, ToolRunResult
from ..policies import check_output_prefix, check_prepfold_dm, check_prepfold_period

log = logging.getLogger("presto_mcp.tools.prepfold")

DEFAULT_PREFIX = "fold"


def _result_parser_factory(prefix: str) -> Callable[[str, Path], PrepfoldResult]:
    def parser(_stdout: str, run_dir: Path) -> PrepfoldResult:
        artifacts = run_dir / "artifacts"

        def first(suffix: str) -> str | None:
            hits = sorted(artifacts.glob(f"*{suffix}"))
            return hits[0].name if hits else None

        return PrepfoldResult(
            period_s=0.0,  # filled at call site
            dm=0.0,
            output_prefix=prefix,
            pfd_file=first(".pfd"),
            ps_file=first(".pfd.ps"),
            bestprof_file=first(".pfd.bestprof"),
            png_file=first(".pfd.png"),
        )

    return parser


def run_prepfold(
    input_file: str,
    period_s: float,
    dm: float,
    *,
    backend: BackendProtocol,
    output_prefix: str | None = None,
    settings: Settings | None = None,
    background: bool = False,
) -> ToolRunResult[PrepfoldResult]:
    """Mode A: ``prepfold -noxwin -p <period> -dm <dm> -o /outputs/artifacts/<prefix> ...``."""
    s = settings or get_settings()
    p = check_prepfold_period(period_s)
    d = check_prepfold_dm(dm)
    prefix = check_output_prefix(output_prefix or DEFAULT_PREFIX)

    def argv_builder(
        container_input: str, _extras: tuple[str, ...], _run_dir: Path
    ) -> list[str]:
        return [
            "prepfold",
            "-noxwin",
            "-nosearch",
            "-p", str(p),
            "-dm", str(d),
            "-o", f"/outputs/artifacts/{prefix}",
            container_input,
        ]

    parser_fn = _result_parser_factory(prefix)

    def parser(stdout: str, run_dir: Path) -> PrepfoldResult:
        res = parser_fn(stdout, run_dir)
        # Period/dm aren't in stdout; carry from inputs.
        return res.model_copy(update={"period_s": p, "dm": d})

    spec = RunSpec[PrepfoldResult](
        tool_name="prepfold",
        input_file=input_file,
        inputs_extra={"period_s": str(p), "dm": str(d), "output_prefix": prefix},
        container_input_path="",
        presto_argv_builder=argv_builder,
        parser=parser,
        timeout_s=s.default_timeout_s,
        cpus=s.default_cpus,
        memory_mb=s.default_memory_mb,
    )
    return execute(spec, s, backend, background=background)
