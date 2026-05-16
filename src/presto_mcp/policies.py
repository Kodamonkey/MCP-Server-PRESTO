"""Numeric policy guards applied before invoking PRESTO.

Each ``check_*`` raises :class:`PolicyViolationError` on a bad value and returns
the clamped/coerced value on success. Keep these dumb and explicit — no
``isinstance`` ladders, no clever defaults.
"""

from __future__ import annotations

from .errors import PolicyViolationError

MIN_TIMEOUT_S = 1
MAX_TIMEOUT_S = 6 * 60 * 60  # 6 hours

MIN_CPUS = 0.1
MAX_CPUS = 64.0

MIN_MEMORY_MB = 128
MAX_MEMORY_MB = 256 * 1024  # 256 GiB

RFIFIND_MIN_TIME_S = 0.1
RFIFIND_MAX_TIME_S = 3600.0

PREPFOLD_MIN_PERIOD_S = 1e-6
PREPFOLD_MAX_PERIOD_S = 60.0

PREPFOLD_MIN_DM = 0.0
PREPFOLD_MAX_DM = 10_000.0


def check_timeout(timeout_s: int) -> int:
    if not isinstance(timeout_s, int) or isinstance(timeout_s, bool):
        raise PolicyViolationError(f"timeout_s must be int, got {type(timeout_s).__name__}")
    if not (MIN_TIMEOUT_S <= timeout_s <= MAX_TIMEOUT_S):
        raise PolicyViolationError(
            f"timeout_s {timeout_s} outside [{MIN_TIMEOUT_S}, {MAX_TIMEOUT_S}]"
        )
    return timeout_s


def check_cpus(cpus: float) -> float:
    f = float(cpus)
    if not (MIN_CPUS <= f <= MAX_CPUS):
        raise PolicyViolationError(f"cpus {cpus} outside [{MIN_CPUS}, {MAX_CPUS}]")
    return f


def check_memory_mb(memory_mb: int) -> int:
    if not isinstance(memory_mb, int) or isinstance(memory_mb, bool):
        raise PolicyViolationError(
            f"memory_mb must be int, got {type(memory_mb).__name__}"
        )
    if not (MIN_MEMORY_MB <= memory_mb <= MAX_MEMORY_MB):
        raise PolicyViolationError(
            f"memory_mb {memory_mb} outside [{MIN_MEMORY_MB}, {MAX_MEMORY_MB}]"
        )
    return memory_mb


def check_rfifind_time(time_s: float) -> float:
    f = float(time_s)
    if not (RFIFIND_MIN_TIME_S <= f <= RFIFIND_MAX_TIME_S):
        raise PolicyViolationError(
            f"rfifind time {time_s} outside [{RFIFIND_MIN_TIME_S}, {RFIFIND_MAX_TIME_S}]"
        )
    return f


def check_prepfold_period(period_s: float) -> float:
    f = float(period_s)
    if not (PREPFOLD_MIN_PERIOD_S <= f <= PREPFOLD_MAX_PERIOD_S):
        raise PolicyViolationError(
            f"prepfold period {period_s} outside "
            f"[{PREPFOLD_MIN_PERIOD_S}, {PREPFOLD_MAX_PERIOD_S}]"
        )
    return f


def check_prepfold_dm(dm: float) -> float:
    f = float(dm)
    if not (PREPFOLD_MIN_DM <= f <= PREPFOLD_MAX_DM):
        raise PolicyViolationError(
            f"prepfold DM {dm} outside [{PREPFOLD_MIN_DM}, {PREPFOLD_MAX_DM}]"
        )
    return f


_PREFIX_OK = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-+.")


def check_output_prefix(prefix: str) -> str:
    if not isinstance(prefix, str):
        raise PolicyViolationError(
            f"output_prefix must be str, got {type(prefix).__name__}"
        )
    if not prefix:
        raise PolicyViolationError("output_prefix is empty")
    if len(prefix) > 128:
        raise PolicyViolationError(f"output_prefix too long ({len(prefix)} > 128)")
    bad = sorted({c for c in prefix if c not in _PREFIX_OK})
    if bad:
        raise PolicyViolationError(
            f"output_prefix contains forbidden characters: {bad!r}"
        )
    return prefix
