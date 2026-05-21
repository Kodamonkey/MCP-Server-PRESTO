"""``presto.binary_info`` — orbital summary for a binary-pulsar ephemeris.

Utility tool (no Docker, no PRESTO execution): it reads one ``.par`` file and
reports the orbital parameters plus a derived line-of-sight velocity amplitude
and the Doppler-smeared spin period / frequency range an acceleration search
would have to cover. Pure arithmetic — it never asserts a detection.
"""

from __future__ import annotations

import logging
import math

from ..config import Settings, get_settings
from ..models import BinaryInfoResult
from ..parsers import parfile_parser
from ..parsers.parfile_parser import SPEED_OF_LIGHT_M_S
from ..path_security import is_run_artifact_path, resolve_input_path, resolve_run_artifact

log = logging.getLogger("presto_mcp.tools.binary_info")


def _resolve(rel: str, s: Settings):  # type: ignore[no-untyped-def]
    if is_run_artifact_path(rel):
        return resolve_run_artifact(rel, s.runs_dir)
    return resolve_input_path(rel, s.data_dir)


def run_binary_info(
    par_file: str,
    *,
    inf_file: str | None = None,
    make_plot: bool = False,
    settings: Settings | None = None,
) -> BinaryInfoResult:
    """Summarise the orbital parameters of a binary pulsar ephemeris."""
    s = settings or get_settings()
    host_par = _resolve(par_file, s)
    text = host_par.read_text(encoding="utf-8", errors="replace")
    fields = parfile_parser.parse_par_text(text)

    notes: list[str] = []
    if inf_file is not None:
        # Resolve to validate the path; the .inf is not required for the maths.
        _resolve(inf_file, s)
    if make_plot:
        notes.append(
            "make_plot is not supported: presto.binary_info is a no-Docker "
            "utility tool. Use presto.prepfold / pfd2png for orbital plots."
        )

    name = parfile_parser.pulsar_name(fields)
    spin_s = parfile_parser.spin_period_s(fields)
    binary = parfile_parser.is_binary(fields)

    summary: dict[str, float | str | None] = {
        "pulsar_name": name,
        "spin_period_s": spin_s,
        "spin_frequency_hz": (1.0 / spin_s) if spin_s else None,
        "binary_model": fields.get("BINARY"),
    }

    if not binary:
        notes.append("ephemeris has no binary parameters — isolated pulsar")
        return BinaryInfoResult(
            par_file=par_file,
            inf_file=inf_file,
            is_binary=False,
            pulsar_name=name,
            binary_summary=summary,
            plot_files=[],
            notes=notes,
        )

    pb_s = parfile_parser.orbital_period_s(fields)
    a1_lt_s = parfile_parser.as_float(fields.get("A1"))
    ecc = parfile_parser.eccentricity(fields)
    summary.update(
        {
            "orbital_period_s": pb_s,
            "orbital_period_days": (pb_s / 86_400.0) if pb_s else None,
            "projected_semi_major_axis_lt_s": a1_lt_s,
            "eccentricity": ecc,
            "longitude_periastron_deg": parfile_parser.as_float(fields.get("OM")),
            "epoch_periastron_mjd": parfile_parser.as_float(fields.get("T0")),
            "epoch_asc_node_mjd": parfile_parser.as_float(fields.get("TASC")),
        }
    )

    if pb_s and a1_lt_s and pb_s > 0:
        e = ecc if (ecc is not None and 0.0 <= ecc < 1.0) else 0.0
        # K = 2*pi * (a1*c) / PB / sqrt(1-e^2): line-of-sight velocity amplitude.
        k_m_s = (
            2.0 * math.pi * a1_lt_s * SPEED_OF_LIGHT_M_S / pb_s
        ) / math.sqrt(1.0 - e * e)
        summary["radial_velocity_amplitude_km_s"] = k_m_s / 1000.0
        if spin_s:
            doppler = k_m_s / SPEED_OF_LIGHT_M_S
            p_min = spin_s * (1.0 - doppler)
            p_max = spin_s * (1.0 + doppler)
            summary["observed_period_min_ms"] = p_min * 1000.0
            summary["observed_period_max_ms"] = p_max * 1000.0
            summary["observed_freq_min_hz"] = 1.0 / p_max
            summary["observed_freq_max_hz"] = 1.0 / p_min
    else:
        notes.append(
            "PB and A1 not both present — cannot derive a velocity amplitude"
        )

    return BinaryInfoResult(
        par_file=par_file,
        inf_file=inf_file,
        is_binary=True,
        pulsar_name=name,
        binary_summary=summary,
        plot_files=[],
        notes=notes,
    )


__all__ = ["run_binary_info"]
