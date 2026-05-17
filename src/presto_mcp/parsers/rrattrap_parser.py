"""Parse PRESTO ``rrattrap.py`` output into a typed :class:`RrattrapResult`.

rrattrap.py groups events from ``*.singlepulse`` files and writes a
``groups.txt`` (configurable filename) into its working directory. The
working directory is the run's ``artifacts/``.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from ..errors import ParserError
from ..models import RrattrapResult

log = logging.getLogger("presto_mcp.parsers.rrattrap")

_BOM = "﻿"
_GROUP_LINE_RE = re.compile(r"^\s*Group\s+(\d+)\b", re.IGNORECASE)


def _count_groups_from_text(path: Path) -> int | None:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    count = 0
    for line in text.splitlines():
        if _GROUP_LINE_RE.match(line):
            count += 1
    return count if count > 0 else None


def parse(
    stdout: str,
    run_dir: Path | None = None,
    *,
    input_singlepulse_files: tuple[str, ...] = (),
    inf_file: str | None = None,
) -> RrattrapResult:
    if not isinstance(stdout, str):
        raise ParserError(f"stdout must be str, got {type(stdout).__name__}")
    if stdout.startswith(_BOM):
        stdout = stdout[1:]

    groups_file: str | None = None
    num_groups: int | None = None
    output_files: list[str] = []

    if run_dir is not None:
        artifacts_dir = run_dir / "artifacts"
        if artifacts_dir.is_dir():
            for pattern in ("*groups*.txt", "groups.txt"):
                hits = sorted(artifacts_dir.glob(pattern))
                if hits:
                    groups_file = hits[0].name
                    num_groups = _count_groups_from_text(hits[0])
                    break
            output_files = sorted(
                p.name
                for p in artifacts_dir.iterdir()
                if p.is_file() and p.suffix in {".txt", ".ps", ".png"}
            )

    return RrattrapResult(
        input_singlepulse_files=list(input_singlepulse_files),
        inf_file=inf_file,
        groups_file=groups_file,
        num_groups=num_groups,
        output_files=output_files,
    )
