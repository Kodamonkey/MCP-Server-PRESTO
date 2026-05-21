"""Minimal pulsar ephemeris (``.par``) parser. Standard library only.

A ``.par`` file is whitespace-delimited: ``KEY VALUE [FIT_FLAG] [ERROR]``. We
keep only ``KEY -> first value`` and expose a few physically-derived getters.
This deliberately does NOT depend on ``presto.parfile`` so the pure-Python
utility tools (``compare_periods``, ``binary_info``) work without Docker.
"""

from __future__ import annotations

SPEED_OF_LIGHT_M_S = 299_792_458.0
SECONDS_PER_DAY = 86_400.0


def parse_par_text(text: str) -> dict[str, str]:
    """Parse ``.par`` text into an uppercase ``KEY -> first-value`` dict."""
    fields: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        # PRESTO/TEMPO comment lines start with a bare 'C'.
        if parts[0].upper() == "C":
            continue
        if len(parts) < 2:
            continue
        key = parts[0].upper()
        fields.setdefault(key, parts[1])
    return fields


def as_float(value: str | None) -> float | None:
    """Float-parse a par value, tolerating Fortran ``D`` exponents."""
    if value is None:
        return None
    try:
        return float(value.replace("D", "e").replace("d", "e"))
    except ValueError:
        return None


def pulsar_name(fields: dict[str, str]) -> str | None:
    return fields.get("PSRJ") or fields.get("PSR") or fields.get("PSRB")


def spin_period_s(fields: dict[str, str]) -> float | None:
    """Spin period (s) from ``P0`` or ``1/F0``."""
    p0 = as_float(fields.get("P0"))
    if p0 and p0 > 0:
        return p0
    f0 = as_float(fields.get("F0"))
    if f0 and f0 > 0:
        return 1.0 / f0
    return None


def is_binary(fields: dict[str, str]) -> bool:
    return "BINARY" in fields or "PB" in fields or "FB0" in fields


def orbital_period_s(fields: dict[str, str]) -> float | None:
    """Orbital period (s) from ``PB`` (days) or ``1/FB0``."""
    pb_days = as_float(fields.get("PB"))
    if pb_days and pb_days > 0:
        return pb_days * SECONDS_PER_DAY
    fb0 = as_float(fields.get("FB0"))
    if fb0 and fb0 > 0:
        return 1.0 / fb0
    return None


def eccentricity(fields: dict[str, str]) -> float | None:
    """Eccentricity from ``ECC``/``E`` or the ELL1 ``EPS1``/``EPS2`` pair."""
    for key in ("ECC", "E"):
        e = as_float(fields.get(key))
        if e is not None:
            return e
    eps1 = as_float(fields.get("EPS1"))
    eps2 = as_float(fields.get("EPS2"))
    if eps1 is not None and eps2 is not None:
        return (eps1 * eps1 + eps2 * eps2) ** 0.5
    return None
