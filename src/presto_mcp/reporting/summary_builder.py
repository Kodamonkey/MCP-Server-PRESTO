"""Build ``summary.json`` (:class:`RunReportSummary`) from a PRESTO workdir.

Observation metadata is extracted, in priority order, from:

  1. a ``readfile`` run's ``stdout.log`` (reuses the readfile stdout parser),
  2. otherwise the first PRESTO ``.inf`` file found.

Operational metadata (tools executed, failed tools, runtime) comes from the
``manifest.json`` of each per-tool run directory. Nothing is assumed about the
science content — the file is never claimed to contain a pulsar/FRB/RRAT.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from ..parsers.readfile_parser import parse as parse_readfile
from .schemas import (
    ArtifactPolicy,
    Candidate,
    CandidateCounts,
    CandidateType,
    ObservationMetadata,
    RfiSummary,
    RunReportSummary,
)

log = logging.getLogger("presto_mcp.reporting.summary_builder")

_FAILED_STATUSES = {"FAILED", "TIMEOUT"}
_NON_BLOCKING_WARNING_PREFIXES = (
    "Ghostscript not found; .ps/.eps plots were not converted to PNG.",
)


def build_summary(
    *,
    run_id: str,
    input_file: str | None,
    roots: list[Path],
    candidates: list[Candidate],
    policy: ArtifactPolicy,
    generated_at: datetime,
    warnings: list[str] | None = None,
    errors: list[str] | None = None,
    top_n: int = 10,
    logs_available: bool = False,
    status_file: str | None = None,
) -> RunReportSummary:
    """Assemble a :class:`RunReportSummary` for one report bundle."""
    warnings = list(warnings or [])
    errors = list(errors or [])

    manifests = _scan_run_manifests(roots)
    tools_executed = sorted({m["tool"] for m in manifests if m.get("tool")})
    failed_tools = sorted(
        {
            m["tool"]
            for m in manifests
            if m.get("tool") and str(m.get("status", "")).upper() in _FAILED_STATUSES
        }
    )
    total_runtime = sum(
        float(m["duration_s"]) for m in manifests if isinstance(m.get("duration_s"), int | float)
    )
    peak_memory = _peak_memory_mb(manifests)

    if input_file is None:
        input_file = _first_input_file(manifests)

    observation = _observation_metadata(roots, manifests, warnings)
    counts = _candidate_counts(candidates)
    top = sorted(candidates, key=lambda c: (c.rank is None, c.rank or 1_000_000))[:top_n]
    rfi = _rfi_summary(roots)

    blocking_warnings = [w for w in warnings if _is_blocking_warning(w)]

    status: str = "success"
    if errors or failed_tools:
        status = "failed" if errors else "partial"
    elif blocking_warnings:
        status = "partial"

    return RunReportSummary(
        run_id=run_id,
        input_file=input_file,
        generated_at=generated_at,
        status=status,  # type: ignore[arg-type]
        observation=observation,
        dm_trials=None,
        candidate_counts=counts,
        top_candidates=top,
        rfi_summary=rfi,
        tools_executed=tools_executed,
        failed_tools=failed_tools,
        artifact_policy=policy,
        total_runtime_sec=round(total_runtime, 3) if total_runtime else None,
        peak_memory_mb=peak_memory,
        warning_count=len(warnings),
        error_count=len(errors),
        logs_available=logs_available,
        status_file=status_file,
        warnings=warnings,
        errors=errors,
    )


def _is_blocking_warning(message: str) -> bool:
    """Return ``True`` when a warning should degrade overall run status."""
    text = (message or "").strip()
    if not text:
        return False
    return not any(text.startswith(prefix) for prefix in _NON_BLOCKING_WARNING_PREFIXES)


# -- run-manifest discovery ----------------------------------------------------


def _scan_run_manifests(roots: list[Path]) -> list[dict]:
    """Return parsed per-tool ``manifest.json`` documents found under ``roots``."""
    out: list[dict] = []
    for root in roots:
        root = Path(root)
        if not root.exists():
            continue
        targets = [root / "manifest.json"] if root.is_dir() else []
        if root.is_dir():
            targets += sorted(root.rglob("manifest.json"))
        for mpath in dict.fromkeys(targets):  # dedupe, keep order
            if not mpath.is_file():
                continue
            try:
                data = json.loads(mpath.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            # A per-tool run manifest has "tool" + "presto_argv"; skip report
            # manifests (which carry "artifact_policy").
            if isinstance(data, dict) and data.get("tool") and "artifact_policy" not in data:
                out.append(data)
    return out


def _peak_memory_mb(manifests: list[dict]) -> float | None:
    """Max ``resource_usage.peak_memory_mb`` across per-tool manifests (None if absent)."""
    peaks: list[float] = []
    for m in manifests:
        usage = m.get("resource_usage")
        if isinstance(usage, dict):
            val = usage.get("peak_memory_mb")
            if isinstance(val, int | float):
                peaks.append(float(val))
    return round(max(peaks), 1) if peaks else None


def _first_input_file(manifests: list[dict]) -> str | None:
    for m in manifests:
        inputs = m.get("inputs")
        if isinstance(inputs, dict):
            ref = inputs.get("input_file")
            if isinstance(ref, str) and ref.strip():
                return ref
    return None


# -- observation metadata ------------------------------------------------------


def _observation_metadata(
    roots: list[Path],
    manifests: list[dict],
    warnings: list[str],
) -> ObservationMetadata:
    md = _metadata_from_readfile(roots, manifests)
    if md is not None:
        return md
    md = _metadata_from_inf(roots)
    if md is not None:
        return md
    warnings.append("no readfile output or .inf file found; observation metadata is empty")
    return ObservationMetadata()


def _metadata_from_readfile(
    roots: list[Path], manifests: list[dict]
) -> ObservationMetadata | None:
    for root in roots:
        root = Path(root)
        if not root.is_dir():
            continue
        for mpath in [root / "manifest.json", *sorted(root.rglob("manifest.json"))]:
            if not mpath.is_file():
                continue
            try:
                data = json.loads(mpath.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(data, dict) or data.get("tool") != "readfile":
                continue
            stdout_path = mpath.parent / str(data.get("stdout_path", "stdout.log"))
            if not stdout_path.is_file():
                continue
            try:
                meta = parse_readfile(stdout_path.read_text(encoding="utf-8", errors="replace"))
            except Exception as e:  # noqa: BLE001,S112 - parser is best-effort here
                log.debug("readfile parse skipped for %s: %s", stdout_path, e)
                continue
            return ObservationMetadata(
                file_type=meta.file_format,
                telescope=meta.telescope,
                source_name=meta.source_name,
                mjd_start=meta.mjd_start,
                nchans=meta.num_channels,
                tsamp_us=meta.sample_time_us,
                fch1_mhz=meta.low_channel_mhz,
                central_freq_mhz=meta.central_freq_mhz,
                bandwidth_mhz=meta.total_bandwidth_mhz,
                duration_sec=meta.duration_s,
                bits_per_sample=meta.bits_per_sample,
            )
    return None


def _metadata_from_inf(roots: list[Path]) -> ObservationMetadata | None:
    for root in roots:
        root = Path(root)
        if not root.is_dir():
            continue
        for inf in sorted(root.rglob("*.inf")):
            fields = _parse_inf(inf)
            if not fields:
                continue
            bin_w = _find_float(fields, "width of each time series bin")
            nbins = _find_float(fields, "number of bins in the time series")
            low = _find_float(fields, "central freq of low channel")
            bw = _find_float(fields, "total bandwidth")
            return ObservationMetadata(
                file_type="PRESTO .inf (dedispersed time series)",
                telescope=_find_str(fields, "telescope"),
                instrument=_find_str(fields, "instrument"),
                source_name=_find_str(fields, "object being observed"),
                mjd_start=_find_float(fields, "epoch of observation"),
                nchans=_find_int(fields, "number of channels"),
                tsamp_us=(bin_w * 1e6) if bin_w is not None else None,
                fch1_mhz=low,
                central_freq_mhz=(low + bw / 2.0) if (low is not None and bw is not None) else None,
                bandwidth_mhz=bw,
                duration_sec=(nbins * bin_w) if (nbins is not None and bin_w is not None) else None,
            )
    return None


def _parse_inf(path: Path) -> dict[str, str]:
    fields: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return fields
    for line in text.splitlines():
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip().lower()
        value = value.strip()
        if key and value:
            fields[key] = value
    return fields


def _find_str(fields: dict[str, str], substr: str) -> str | None:
    for key, value in fields.items():
        if substr in key:
            return value or None
    return None


def _find_float(fields: dict[str, str], substr: str) -> float | None:
    raw = _find_str(fields, substr)
    if raw is None:
        return None
    try:
        return float(raw.split()[0])
    except (ValueError, IndexError):
        return None


def _find_int(fields: dict[str, str], substr: str) -> int | None:
    val = _find_float(fields, substr)
    return int(val) if val is not None else None


# -- candidate counts / RFI ----------------------------------------------------


def _candidate_counts(candidates: list[Candidate]) -> CandidateCounts:
    counts = CandidateCounts(total=len(candidates))
    for c in candidates:
        if c.candidate_type == CandidateType.SINGLE_PULSE:
            counts.single_pulse += 1
        elif c.candidate_type == CandidateType.PERIODIC:
            counts.periodic += 1
        elif c.candidate_type == CandidateType.ACCELERATION:
            counts.acceleration += 1
        elif c.candidate_type == CandidateType.FOLDED:
            counts.folded += 1
        elif c.candidate_type == CandidateType.RRAT_GROUP:
            counts.rrat_group += 1
        else:
            counts.unknown += 1
    return counts


def _rfi_summary(roots: list[Path]) -> RfiSummary:
    mask_files: list[str] = []
    for root in roots:
        root = Path(root)
        if not root.is_dir():
            continue
        for p in sorted(root.rglob("*")):
            if p.is_file() and p.suffix.lower() in {".mask", ".rfi", ".stats"}:
                mask_files.append(p.name)
    notes: list[str] = []
    if mask_files:
        notes.append("bad-channel / bad-interval detail requires rfifind_stats parsing")
    return RfiSummary(
        available=bool(mask_files),
        mask_files=sorted(set(mask_files)),
        notes=notes,
    )


__all__ = ["build_summary"]
