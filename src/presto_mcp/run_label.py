"""Human-readable labels for runs.

``run_id`` (``20260531T014921Z-2HKYMX``) is the stable physical key but tells a
human nothing. These helpers derive a self-describing label from the tool name +
its input observation, in the spirit of PRESTO's basename-prefixed filenames.
Pure functions, no I/O.
"""

from __future__ import annotations

from pathlib import PurePosixPath

# Compound suffixes whose final component alone would be a poor observation name.
_DOUBLE_SUFFIXES = (".fits.gz", ".fil.gz", ".tar.gz")


def observation_basename(inputs: dict[str, str] | None) -> str | None:
    """Return the observation stem from ``inputs['input_file']``, else None.

    Strips directories and the file extension:
    ``57762_12049_J0532+3305_000022.fil`` -> ``57762_12049_J0532+3305_000022``.
    """
    if not inputs:
        return None
    ref = inputs.get("input_file")
    if not isinstance(ref, str) or not ref.strip():
        return None
    # Normalize both separator flavors; take the final path component.
    name = PurePosixPath(ref.strip().replace("\\", "/")).name
    if not name:
        return None
    lowered = name.lower()
    for suf in _DOUBLE_SUFFIXES:
        if lowered.endswith(suf):
            return name[: -len(suf)] or None
    stem = PurePosixPath(name).stem  # drops the last extension only
    return stem or name


def run_label(tool: str, inputs: dict[str, str] | None) -> str:
    """Return ``<observation>__<tool>``, or just ``<tool>`` when no input.

    e.g. ``57762_12049_J0532+3305_000022__rfifind`` / ``ddplan``.
    """
    obs = observation_basename(inputs)
    return f"{obs}__{tool}" if obs else tool


def safe_dir_component(name: str) -> str:
    """Sanitize ``name`` into a single filesystem-safe path component."""
    cleaned = "".join(
        ch if (ch.isalnum() or ch in {"_", "-", "."}) else "_" for ch in name
    ).strip("._")
    return cleaned or "report"


def report_bundle_dirname(input_file: str | None, timestamp: str) -> str:
    """Readable outputs/ bundle folder name: ``<observation>__<timestamp>``.

    ``timestamp`` is a precomputed ``YYYYMMDDTHHMMSSZ`` string. Falls back to
    ``report__<timestamp>`` when there is no input observation.
    """
    obs = observation_basename({"input_file": input_file or ""})
    base = safe_dir_component(obs) if obs else "report"
    return f"{base}__{timestamp}"


__all__ = [
    "observation_basename",
    "report_bundle_dirname",
    "run_label",
    "safe_dir_component",
]
