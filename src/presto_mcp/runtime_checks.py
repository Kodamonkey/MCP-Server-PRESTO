"""Runtime capability probes for the configured PRESTO Docker image.

The pinned image (``alex88ridolfi/presto5:png`` or a successor) does not always
provide every PRESTO routine, and some scripts that *are* present cannot import
their internal Python modules (confirmed: ``rrattrap.py`` exists but
``import presto.singlepulse`` fails). This module turns that into structured
readiness data instead of confusing tracebacks.

Probes are lightweight one-off Docker commands only — ``which <binary>``,
``python3 -c "import ..."``, ``<binary> -h``. They never run real PRESTO work.
They reuse the proven invocation path (:func:`build_invocation` +
``backend.run``) so there is no new subprocess surface and no change to
``BackendProtocol``.

Individual check results are cached in-process, keyed by ``(image, check)``
with a short TTL, so a preflight gate (one tool, 2-3 deps) is cheap and a full
``validate_environment`` sweep reuses everything it already probed.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from datetime import UTC, datetime

from .config import Settings
from .docker_backend import BackendProtocol, build_invocation
from .models import (
    PrestoRuntimeCapabilities,
    RunStatus,
    RuntimeCheck,
    RuntimeCheckStatus,
    RuntimeCompatibilityResult,
    ToolReadiness,
)

log = logging.getLogger("presto_mcp.runtime_checks")

_PROBE_TIMEOUT_S = 12
_HELP_TIMEOUT_S = 15
_CACHE_TTL_S = 900  # 15 min — an image tag's contents are immutable per session
_RAW_OUTPUT_CLIP = 600
_HELP_MIN_CHARS = 40  # below this, a `-h` probe is treated as "binary absent"

# Static dependency table: the single source of truth for tool -> runtime deps.
# Each entry maps a tool name to (required binaries, required python modules).
# Tools whose binary lives off PATH (e.g. ACCEL_sift.py under examplescripts)
# are intentionally omitted — a `which` probe would be misleading for them.
_TOOL_DEPS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "readfile": (("readfile",), ()),
    "rfifind": (("rfifind",), ()),
    "rfifind_stats": (("rfifind_stats.py",), ()),
    "prepdata": (("prepdata",), ()),
    "prepsubband": (("prepsubband",), ()),
    "ddplan": (("DDplan.py",), ()),
    "realfft": (("realfft",), ()),
    "accelsearch": (("accelsearch",), ()),
    "prepfold": (("prepfold",), ()),
    "zapbirds": (("zapbirds",), ()),
    "single_pulse_search": (("single_pulse_search.py",), ("presto.singlepulse",)),
    "rrattrap": (("rrattrap.py",), ("presto.singlepulse",)),
    "make_spd": (("make_spd.py",), ("presto.singlepulse",)),
    "plot_spd": (("plot_spd.py",), ()),
    "waterfaller": (("waterfaller.py",), ("presto.waterfaller",)),
    "get_toas": (("get_TOAs.py",), ()),
    "psrfits2fil": (("psrfits2fil.py",), ("presto.psrfits",)),
    "downsample_filterbank": (("downsample_filterbank.py",), ()),
    "fb_truncate": (("fb_truncate.py",), ()),
    "weights_to_ignorechan": (("weights_to_ignorechan.py",), ()),
    "makezaplist": (("makezaplist.py",), ()),
    "sum_profiles": (("sum_profiles.py",), ()),
    "search_bin": (("search_bin",), ()),
    "stacksearch": (("stacksearch.py",), ()),
    "simple_zapbirds": (("simple_zapbirds.py",), ()),
    "compare_periods": (("compare_periods.py",), ("presto.parfile",)),
    "binary_info": (("binary_info.py",), ("presto.parfile",)),
}


def all_tool_names() -> tuple[str, ...]:
    """Tool names that have a runtime-dependency entry, sorted."""
    return tuple(sorted(_TOOL_DEPS))


def tool_dependencies(tool_name: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return ``(required_binaries, required_python_modules)`` for one tool."""
    return _TOOL_DEPS.get(tool_name, ((), ()))


# -- in-process cache (per individual check) ------------------------------------

# key -> (RuntimeCheck, monotonic_expiry); help entries also carry the help text.
_CHECK_CACHE: dict[tuple[str, str], tuple[RuntimeCheck, float]] = {}
_HELP_CACHE: dict[tuple[str, str], tuple[RuntimeCheck, str, float]] = {}
_CACHE_LOCK = threading.Lock()


def clear_runtime_cache() -> None:
    """Drop all cached probe results. Test hook / force-refresh helper."""
    with _CACHE_LOCK:
        _CHECK_CACHE.clear()
        _HELP_CACHE.clear()


# -- low-level probe ------------------------------------------------------------


def _clip(text: str) -> str | None:
    text = " ".join((text or "").split())
    if not text:
        return None
    if len(text) <= _RAW_OUTPUT_CLIP:
        return text
    return text[: _RAW_OUTPUT_CLIP - 3] + "..."


def _run_probe(
    backend: BackendProtocol,
    settings: Settings,
    probe_argv: list[str],
    timeout_s: int,
) -> tuple[RunStatus, str, str]:
    """Run one lightweight probe command in the PRESTO image. Never raises."""
    invocation = build_invocation(
        image=settings.image,
        presto_argv=probe_argv,
        data_dir=settings.data_dir,
        run_dir=settings.outputs_dir,
        cpus=settings.default_cpus,
        memory_mb=settings.default_memory_mb,
        container_name=f"presto-probe-{time.time_ns()}",
    )
    try:
        result = backend.run(invocation, timeout_s=timeout_s)
    except Exception as e:  # noqa: BLE001 - probes must never raise
        log.warning("runtime probe backend error for %r: %s", probe_argv, e)
        return RunStatus.FAILED, "", f"probe backend error: {type(e).__name__}: {e}"
    return result.status, result.stdout or "", result.stderr or ""


# -- individual checks ----------------------------------------------------------


def check_binary_available(
    backend: BackendProtocol,
    settings: Settings,
    name: str,
    *,
    timeout_s: int = _PROBE_TIMEOUT_S,
    force_refresh: bool = False,
) -> RuntimeCheck:
    """Probe ``which <name>`` inside the image. Cached per (image, binary)."""
    key = (settings.image, f"binary.{name}")
    if not force_refresh:
        cached = _cache_get(_CHECK_CACHE, key)
        if cached is not None:
            return cached[0]

    status, out, err = _run_probe(backend, settings, ["which", name], timeout_s)
    check_name = f"binary.{name}"
    if status == RunStatus.SUCCESS:
        check = RuntimeCheck(
            name=check_name,
            kind="binary",
            status="OK",
            message=f"{name} is on PATH",
            raw_output=_clip(out),
        )
    elif status == RunStatus.TIMEOUT:
        check = RuntimeCheck(
            name=check_name,
            kind="binary",
            status="UNKNOWN",
            message=f"probe for {name} timed out after {timeout_s}s",
            remediation="Re-run presto.validate_environment when Docker is responsive.",
        )
    else:
        check = RuntimeCheck(
            name=check_name,
            kind="binary",
            status="ERROR",
            message=f"{name} is not on PATH in image {settings.image}",
            remediation=(
                f"Use a PRESTO image that provides {name}, or avoid tools "
                f"that need it."
            ),
            raw_output=_clip(err or out),
        )
    _cache_put(_CHECK_CACHE, key, (check, _deadline()))
    return check


def check_python_module_available(
    backend: BackendProtocol,
    settings: Settings,
    module: str,
    *,
    timeout_s: int = _HELP_TIMEOUT_S,
    force_refresh: bool = False,
) -> RuntimeCheck:
    """Probe ``python3 -c "find_spec(<module>)"``. Cached per (image, module)."""
    key = (settings.image, f"module.{module}")
    if not force_refresh:
        cached = _cache_get(_CHECK_CACHE, key)
        if cached is not None:
            return cached[0]

    code = (
        "import importlib.util as u; "
        f"raise SystemExit(0 if u.find_spec({module!r}) else 1)"
    )
    status, out, err = _run_probe(
        backend, settings, ["python3", "-c", code], timeout_s
    )
    check_name = f"module.{module}"
    if status == RunStatus.SUCCESS:
        check = RuntimeCheck(
            name=check_name,
            kind="python_module",
            status="OK",
            message=f"python module {module} is importable",
        )
    elif status == RunStatus.TIMEOUT:
        check = RuntimeCheck(
            name=check_name,
            kind="python_module",
            status="UNKNOWN",
            message=f"probe for module {module} timed out after {timeout_s}s",
            remediation="Re-run presto.validate_environment when Docker is responsive.",
        )
    else:
        check = RuntimeCheck(
            name=check_name,
            kind="python_module",
            status="ERROR",
            message=(
                f"python module {module} cannot be imported in image "
                f"{settings.image}"
            ),
            remediation=(
                f"This is a PRESTO image/runtime issue. Use an image where "
                f"{module} imports cleanly, or skip tools that depend on it."
            ),
            raw_output=_clip(err or out),
        )
    _cache_put(_CHECK_CACHE, key, (check, _deadline()))
    return check


def check_binary_help(
    backend: BackendProtocol,
    settings: Settings,
    name: str,
    *,
    timeout_s: int = _HELP_TIMEOUT_S,
    force_refresh: bool = False,
) -> tuple[RuntimeCheck, str]:
    """Probe ``<name> -h`` inside the image. Returns (check, captured help text).

    PRESTO binaries are inconsistent: C tools often print usage to stderr and
    exit non-zero; Python scripts print to stdout and exit 0. We therefore treat
    "produced a meaningful amount of text" as OK regardless of exit code.
    """
    key = (settings.image, f"help.{name}")
    if not force_refresh:
        with _CACHE_LOCK:
            entry = _HELP_CACHE.get(key)
        if entry is not None and entry[2] > time.monotonic():
            return entry[0], entry[1]

    status, out, err = _run_probe(backend, settings, [name, "-h"], timeout_s)
    help_text = f"{out}\n{err}".strip()
    check_name = f"help.{name}"
    if status == RunStatus.TIMEOUT:
        check = RuntimeCheck(
            name=check_name,
            kind="help",
            status="UNKNOWN",
            message=f"`{name} -h` timed out after {timeout_s}s",
            remediation="Re-run when Docker is responsive.",
        )
        help_text = ""
    elif len(help_text) >= _HELP_MIN_CHARS:
        check = RuntimeCheck(
            name=check_name,
            kind="help",
            status="OK",
            message=f"`{name} -h` produced usage text",
            raw_output=_clip(help_text),
        )
    else:
        check = RuntimeCheck(
            name=check_name,
            kind="help",
            status="ERROR",
            message=f"`{name} -h` produced no usage text (binary likely missing)",
            remediation=f"Use a PRESTO image that provides {name}.",
            raw_output=_clip(help_text),
        )
    with _CACHE_LOCK:
        _HELP_CACHE[key] = (check, help_text, _deadline())
    return check, help_text


_FLAG_TOKEN_RE_CACHE: dict[str, re.Pattern[str]] = {}


def check_flag_supported(help_text: str, flag: str) -> bool:
    r"""Return True if ``flag`` appears as a distinct token in ``help_text``.

    Whitespace-tolerant substring scan. A flag like ``-wmax`` must not match
    inside ``-wmaxes``; it is bounded by non ``[\w-]`` characters.
    """
    if not help_text or not flag:
        return False
    pat = _FLAG_TOKEN_RE_CACHE.get(flag)
    if pat is None:
        pat = re.compile(rf"(?<![\w-]){re.escape(flag)}(?![\w-])")
        _FLAG_TOKEN_RE_CACHE[flag] = pat
    return pat.search(help_text) is not None


# -- cache helpers --------------------------------------------------------------


def _deadline() -> float:
    return time.monotonic() + _CACHE_TTL_S


def _cache_get(
    cache: dict[tuple[str, str], tuple[RuntimeCheck, float]],
    key: tuple[str, str],
) -> tuple[RuntimeCheck, float] | None:
    with _CACHE_LOCK:
        entry = cache.get(key)
    if entry is not None and entry[1] > time.monotonic():
        return entry
    return None


def _cache_put(
    cache: dict[tuple[str, str], tuple[RuntimeCheck, float]],
    key: tuple[str, str],
    value: tuple[RuntimeCheck, float],
) -> None:
    with _CACHE_LOCK:
        cache[key] = value


# -- aggregation ----------------------------------------------------------------

# Ordering used to pick the worst status. UNKNOWN sits below ERROR so a
# transient probe failure never blocks a tool (fail-open).
_STATUS_RANK: dict[RuntimeCheckStatus, int] = {
    "OK": 0,
    "WARN": 1,
    "UNKNOWN": 2,
    "ERROR": 3,
}


def _worst(statuses: list[RuntimeCheckStatus]) -> RuntimeCheckStatus:
    if not statuses:
        return "UNKNOWN"
    worst_rank = max(_STATUS_RANK[s] for s in statuses)
    for status, rank in _STATUS_RANK.items():
        if rank == worst_rank:
            return status
    return "UNKNOWN"


def collect_presto_capabilities(
    backend: BackendProtocol,
    settings: Settings,
    *,
    force_refresh: bool = False,
) -> PrestoRuntimeCapabilities:
    """Probe the deduplicated union of all tool dependencies (cached per check)."""
    all_binaries = sorted({b for bins, _ in _TOOL_DEPS.values() for b in bins})
    all_modules = sorted({m for _, mods in _TOOL_DEPS.values() for m in mods})

    keys = [(settings.image, f"binary.{b}") for b in all_binaries]
    keys += [(settings.image, f"module.{m}") for m in all_modules]
    all_cached = not force_refresh and all(
        _cache_get(_CHECK_CACHE, k) is not None for k in keys
    )

    binary_checks = [
        check_binary_available(backend, settings, b, force_refresh=force_refresh)
        for b in all_binaries
    ]
    module_checks = [
        check_python_module_available(
            backend, settings, m, force_refresh=force_refresh
        )
        for m in all_modules
    ]

    return PrestoRuntimeCapabilities(
        image=settings.image,
        checked_at=datetime.now(UTC),
        from_cache=all_cached,
        binaries=binary_checks,
        python_modules=module_checks,
    )


def get_tool_readiness(
    backend: BackendProtocol,
    settings: Settings,
    tool_name: str,
    *,
    force_refresh: bool = False,
) -> ToolReadiness:
    """Aggregate the capability checks one tool depends on.

    Only that tool's 2-3 dependencies are probed (each cached), so this is a
    cheap preflight gate — it does not sweep the whole image.
    """
    req_bins, req_mods = _TOOL_DEPS.get(tool_name, ((), ()))
    checks: list[RuntimeCheck] = [
        check_binary_available(backend, settings, b, force_refresh=force_refresh)
        for b in req_bins
    ]
    checks += [
        check_python_module_available(
            backend, settings, m, force_refresh=force_refresh
        )
        for m in req_mods
    ]
    status = _worst([c.status for c in checks]) if checks else "UNKNOWN"
    return ToolReadiness(
        tool_name=tool_name,
        status=status,
        checks=checks,
        blocking=(status == "ERROR"),
    )


def collect_runtime_compatibility(
    backend: BackendProtocol,
    settings: Settings,
    *,
    force_refresh: bool = False,
) -> RuntimeCompatibilityResult:
    """Full image-vs-tools compatibility report (capabilities + per-tool readiness)."""
    caps = collect_presto_capabilities(
        backend, settings, force_refresh=force_refresh
    )
    bin_map = {c.name: c for c in caps.binaries}
    mod_map = {c.name: c for c in caps.python_modules}

    readiness: list[ToolReadiness] = []
    for name in all_tool_names():
        req_bins, req_mods = _TOOL_DEPS[name]
        checks = [bin_map[f"binary.{b}"] for b in req_bins if f"binary.{b}" in bin_map]
        checks += [
            mod_map[f"module.{m}"] for m in req_mods if f"module.{m}" in mod_map
        ]
        status = _worst([c.status for c in checks]) if checks else "UNKNOWN"
        readiness.append(
            ToolReadiness(
                tool_name=name,
                status=status,
                checks=checks,
                blocking=(status == "ERROR"),
            )
        )

    overall = _worst([r.status for r in readiness]) if readiness else "UNKNOWN"
    return RuntimeCompatibilityResult(
        image=settings.image,
        status=overall,
        capabilities=caps,
        tool_readiness=readiness,
    )


__all__ = [
    "all_tool_names",
    "check_binary_available",
    "check_binary_help",
    "check_flag_supported",
    "check_python_module_available",
    "clear_runtime_cache",
    "collect_presto_capabilities",
    "collect_runtime_compatibility",
    "get_tool_readiness",
    "tool_dependencies",
]
