"""``presto.fb_truncate`` — wrap ``fb_truncate.py`` (samples-mode).

Truncate a filterbank to a sample window. Seconds-mode is intentionally not
exposed in this initial impl — convert seconds to samples upstream (or call
``presto.readfile`` first to obtain sample_time) until the seconds path is
validated against the real binary.
"""

from __future__ import annotations

import logging
from pathlib import Path

from ..config import Settings, get_settings
from ..docker_backend import BackendProtocol
from ..errors import PolicyViolationError
from ..executor import RunSpec, execute
from ..models import FbTruncateResult, ToolRunResult
from ..policies import (
    check_output_prefix,
    check_truncate_num_samples,
    check_truncate_start_sample,
)

log = logging.getLogger("presto_mcp.tools.fb_truncate")

DEFAULT_PREFIX = "trunc"


def run_fb_truncate(
    input_file: str,
    *,
    backend: BackendProtocol,
    start_sample: int = 0,
    num_samples: int,
    output_prefix: str | None = None,
    settings: Settings | None = None,
    background: bool = False,
) -> ToolRunResult[FbTruncateResult]:
    """``fb_truncate.py -s <start_sample> -n <num_samples> -o <prefix> <input>``.

    ``num_samples`` is required; ``start_sample`` defaults to 0.
    """
    s = settings or get_settings()
    if num_samples is None:
        raise PolicyViolationError("fb_truncate requires num_samples")
    start = check_truncate_start_sample(int(start_sample))
    n = check_truncate_num_samples(int(num_samples))
    prefix = check_output_prefix(output_prefix or DEFAULT_PREFIX)

    def argv_builder(
        container_input: str, _extras: tuple[str, ...], _run_dir: Path
    ) -> list[str]:
        return [
            "fb_truncate.py",
            "-s", str(start),
            "-n", str(n),
            "-o", f"/outputs/artifacts/{prefix}",
            container_input,
        ]

    def parser(_stdout: str, run_dir: Path) -> FbTruncateResult:
        artifacts_dir = run_dir / "artifacts"
        out_file: str | None = None
        notes: list[str] = []
        if artifacts_dir.is_dir():
            fils = sorted(p.name for p in artifacts_dir.glob(f"{prefix}*.fil"))
            if fils:
                out_file = fils[0]
            else:
                any_fils = sorted(p.name for p in artifacts_dir.glob("*.fil"))
                if any_fils:
                    out_file = any_fils[0]
        if out_file is None:
            notes.append("no truncated .fil produced; check stderr")
        return FbTruncateResult(
            input_file=input_file,
            output_file=out_file,
            output_prefix=prefix,
            start_sample=start,
            num_samples=n,
            notes=notes,
        )

    spec = RunSpec[FbTruncateResult](
        tool_name="fb_truncate",
        input_file=input_file,
        inputs_extra={
            "start_sample": str(start),
            "num_samples": str(n),
            "output_prefix": prefix,
        },
        container_input_path="",
        presto_argv_builder=argv_builder,
        parser=parser,
        timeout_s=s.default_timeout_s,
        cpus=s.default_cpus,
        memory_mb=s.default_memory_mb,
    )
    return execute(spec, s, backend, background=background)
