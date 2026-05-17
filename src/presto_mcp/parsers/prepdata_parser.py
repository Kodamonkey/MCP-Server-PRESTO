"""Parse PRESTO ``prepdata`` stdout into a typed :class:`PrepdataResult`.

prepdata writes one ``<prefix>.dat`` and a sibling ``<prefix>.inf``. We surface
the filenames by globbing the run-dir's ``artifacts/`` (truth on disk) and pull
sample-count / sample-time hints out of stdout where present.
"""

from __future__ import annotations

import contextlib
import logging
import re
from pathlib import Path

from ..errors import ParserError
from ..models import PrepdataResult

log = logging.getLogger("presto_mcp.parsers.prepdata")

_BOM = "﻿"

_TOTAL_POINTS = re.compile(r"Total points.*?:\s*(\d+)", re.IGNORECASE)
_SAMPLE_DT = re.compile(r"Sample dt.*?:\s*([\d.eE+-]+)")


def parse(
    stdout: str,
    run_dir: Path | None = None,
    *,
    dm: float = 0.0,
    output_prefix: str = "",
) -> PrepdataResult:
    if not isinstance(stdout, str):
        raise ParserError(f"stdout must be str, got {type(stdout).__name__}")
    if stdout.startswith(_BOM):
        stdout = stdout[1:]
    if not stdout.strip():
        raise ParserError("prepdata stdout is empty")

    fields: dict[str, object] = {"dm": float(dm), "output_prefix": output_prefix}

    if (m := _TOTAL_POINTS.search(stdout)) is not None:
        with contextlib.suppress(ValueError):
            fields["num_samples"] = int(m.group(1))
    if (m := _SAMPLE_DT.search(stdout)) is not None:
        with contextlib.suppress(ValueError):
            fields["sample_time_s"] = float(m.group(1))

    if run_dir is not None:
        artifacts_dir = run_dir / "artifacts"
        if artifacts_dir.is_dir():
            for ext, key in ((".dat", "dat_file"), (".inf", "inf_file")):
                hits = sorted(artifacts_dir.glob(f"*{ext}"))
                if hits:
                    fields[key] = hits[0].name

    return PrepdataResult(**fields)  # type: ignore[arg-type]
