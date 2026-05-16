"""Parse PRESTO ``rfifind`` stdout into a typed :class:`RfifindSummary`.

The binary outputs (``.mask``, ``.stats``, ``.rfi``) are NOT parsed here. The
executor records them as artifacts and surfaces them as MCP resources. This
parser only extracts the high-level summary visible in stdout, plus the
filenames PRESTO declared it would write (which we then verify on disk).
"""

from __future__ import annotations

import contextlib
import logging
import re
from pathlib import Path

from ..errors import ParserError
from ..models import RfifindSummary

log = logging.getLogger("presto_mcp.parsers.rfifind")

_BOM = "﻿"

# Quick header KV pairs. rfifind uses "Center freq" (different from readfile).
_HEADER_INT = re.compile(r"^\s*Num of channels\s*=\s*(\d+)\s*$", re.MULTILINE)
_HEADER_SAMPLE = re.compile(r"^\s*Sample time \(s\)\s*=\s*([\d.eE+-]+)", re.MULTILINE)

_TOTAL_INTERVALS = re.compile(
    r"^Total number of intervals in the data:\s*(\d+)\s*$", re.MULTILINE
)
_GOOD = re.compile(r"Number of\s+good\s+intervals:\s*(\d+)\s*\(\s*([\d.]+)%", re.IGNORECASE)
_BAD = re.compile(r"Number of\s+bad\s+intervals:\s*(\d+)\s*\(\s*([\d.]+)%", re.IGNORECASE)
_PADDED = re.compile(r"Number of\s+padded\s+intervals:\s*(\d+)\s*\(\s*([\d.]+)%", re.IGNORECASE)
_RFI = re.compile(r"There are\s+(\d+)\s+RFI instances", re.IGNORECASE)
_WRITE = re.compile(r"Writing\s+(?:mask data|RFI data|statistics)\s+to\s+'([^']+)'")


def parse(stdout: str, run_dir: Path | None = None, time_s: float = 0.0) -> RfifindSummary:
    """Build a :class:`RfifindSummary` from rfifind stdout + optional run_dir.

    ``run_dir`` is used to resolve artifact filenames by globbing
    ``run_dir/artifacts/*.{mask,rfi,stats,ps}`` — more reliable than stdout text
    which uses the container path ``/outputs/...``.
    """
    if not isinstance(stdout, str):
        raise ParserError(f"stdout must be str, got {type(stdout).__name__}")
    if stdout.startswith(_BOM):
        stdout = stdout[1:]
    if not stdout.strip():
        raise ParserError("rfifind stdout is empty")

    fields: dict[str, object] = {"time_s": float(time_s)}

    if (m := _HEADER_INT.search(stdout)) is not None:
        with contextlib.suppress(ValueError):
            fields["num_channels"] = int(m.group(1))

    if (m := _HEADER_SAMPLE.search(stdout)) is not None:
        with contextlib.suppress(ValueError):
            fields["sample_time"] = float(m.group(1))

    if (m := _TOTAL_INTERVALS.search(stdout)) is not None:
        fields["num_intervals"] = int(m.group(1))

    good_pct: float | None = None
    if (m := _GOOD.search(stdout)) is not None:
        fields["good_intervals"] = int(m.group(1))
        try:
            good_pct = float(m.group(2))
        except ValueError:
            good_pct = None
    if (m := _BAD.search(stdout)) is not None:
        fields["bad_intervals"] = int(m.group(1))
    if (m := _RFI.search(stdout)) is not None:
        fields["rfi_instances"] = int(m.group(1))

    if good_pct is not None:
        fields["pct_masked"] = max(0.0, min(100.0, 100.0 - good_pct))

    # Artifact resolution: prefer disk truth over stdout text.
    if run_dir is not None:
        artifacts_dir = run_dir / "artifacts"
        if artifacts_dir.is_dir():
            for ext, key in (
                (".mask", "mask_file"),
                (".rfi", "rfi_file"),
                (".stats", "stats_file"),
                (".ps", "ps_file"),
            ):
                hits = sorted(artifacts_dir.glob(f"*{ext}"))
                if hits:
                    fields[key] = hits[0].name

    # Fallback: pull filenames from stdout if disk gave us nothing.
    if "mask_file" not in fields and (m := _WRITE.search(stdout)) is not None:
        # _WRITE just captures one path; iterate to pick all three.
        for declared in _WRITE.findall(stdout):
            base = declared.split("/")[-1]
            if base.endswith(".mask"):
                fields.setdefault("mask_file", base)
            elif base.endswith(".rfi"):
                fields.setdefault("rfi_file", base)
            elif base.endswith(".stats"):
                fields.setdefault("stats_file", base)

    return RfifindSummary(**fields)  # type: ignore[arg-type]
