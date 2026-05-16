"""Parse PRESTO ``readfile`` stdout into a typed :class:`ReadfileMetadata`.

PRESTO emits a banner line (file format), a ``"<n>: From the <kind> file 'path':"``
header, then key-value lines of the form ``key = value`` (whitespace-padded).
Unknown keys land in ``raw_fields`` so nothing is silently dropped.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from ..errors import ParserError
from ..models import ReadfileMetadata

log = logging.getLogger("presto_mcp.parsers.readfile")

# Drop a UTF-8 BOM if the captured fixture has one.
_BOM = "﻿"

# Known PRESTO readfile keys → ReadfileMetadata field + cast.
_KEY_MAP: dict[str, tuple[str, type | None]] = {
    "Telescope": ("telescope", str),
    "Source Name": ("source_name", str),
    "MJD start time": ("mjd_start", float),
    "RA J2000": ("ra", str),
    "Dec J2000": ("dec", str),
    "Sample time (us)": ("sample_time_us", float),
    "Central freq (MHz)": ("central_freq_mhz", float),
    "Low channel (MHz)": ("low_channel_mhz", float),
    "High channel (MHz)": ("high_channel_mhz", float),
    "Channel width (MHz)": ("channel_width_mhz", float),
    "Number of channels": ("num_channels", int),
    "Total Bandwidth (MHz)": ("total_bandwidth_mhz", float),
    "Time per file (sec)": ("duration_s", float),
    "bits per sample": ("bits_per_sample", int),
}

_FORMAT_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("SIGPROC filterbank", re.compile(r"SIGPROC\s+filterbank", re.IGNORECASE)),
    ("PSRFITS", re.compile(r"PSRFITS", re.IGNORECASE)),
]


def _detect_format(lines: list[str]) -> str | None:
    head = "\n".join(lines[:20])
    for label, pat in _FORMAT_PATTERNS:
        if pat.search(head):
            return label
    return None


def parse(stdout: str, _run_dir: Path | None = None) -> ReadfileMetadata:
    """Parse readfile stdout. Raises :class:`ParserError` only if input is unusable."""
    if not isinstance(stdout, str):
        raise ParserError(f"stdout must be str, got {type(stdout).__name__}")

    if stdout.startswith(_BOM):
        stdout = stdout[1:]

    lines = stdout.splitlines()
    if not lines:
        raise ParserError("readfile stdout is empty")

    file_format = _detect_format(lines)

    raw: dict[str, str] = {}
    typed: dict[str, object] = {}

    for line in lines:
        # Skip the "<n>: From the ... file '...':" header line.
        if "From the" in line and line.rstrip().endswith("':"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        raw[key] = value

        spec = _KEY_MAP.get(key)
        if spec is None:
            continue
        field, caster = spec
        try:
            typed[field] = _cast(value, caster)
        except (ValueError, TypeError) as e:
            log.warning("readfile: failed to cast key=%r value=%r: %s", key, value, e)

    if not raw:
        raise ParserError("readfile stdout contained no 'key = value' pairs")

    return ReadfileMetadata(
        file_format=file_format,
        raw_fields=raw,
        **typed,  # type: ignore[arg-type]
    )


def _cast(value: str, caster: type | None) -> object:
    if caster is None or caster is str:
        return value
    if caster is int:
        return int(value)
    if caster is float:
        return float(value)
    return caster(value)  # type: ignore[call-arg]
