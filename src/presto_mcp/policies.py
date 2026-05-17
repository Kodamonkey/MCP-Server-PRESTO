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

# Shared DM range (used by prepdata/prepsubband/ddplan).
DM_MIN = 0.0
DM_MAX = 10_000.0
DM_RANGE_MAX_SPAN = 5000.0

# accelsearch
ACCELSEARCH_MIN_ZMAX = 0
ACCELSEARCH_MAX_ZMAX = 1200
ACCELSEARCH_VALID_NUMHARM = (1, 2, 4, 8, 16, 32)

# prepsubband / DDplan
SUBBAND_MIN = 1
SUBBAND_MAX = 4096
DM_NUM_MIN = 1
DM_NUM_MAX = 100_000
DM_STEP_MIN = 1e-6
DM_STEP_MAX = 1000.0

# DDplan ranges
DDPLAN_FREQ_MIN_MHZ = 1.0
DDPLAN_FREQ_MAX_MHZ = 1.0e6
DDPLAN_BW_MIN_MHZ = 0.001
DDPLAN_BW_MAX_MHZ = 50_000.0
DDPLAN_SAMPLE_TIME_MIN_US = 1e-3
DDPLAN_SAMPLE_TIME_MAX_US = 1e9

# Single-pulse search
SPS_MIN_THRESHOLD = 1.0
SPS_MAX_THRESHOLD = 50.0
SPS_MIN_WIDTH_S = 1e-6
SPS_MAX_WIDTH_S = 10.0
SPS_MAX_INPUT_FILES = 4096

# Sifting
SIFT_MIN_NUM_DMS_MIN = 1
SIFT_MIN_NUM_DMS_MAX = 1000
SIFT_LOW_DM_CUTOFF_MIN = 0.0
SIFT_LOW_DM_CUTOFF_MAX = 10_000.0
SIFT_SIGMA_MIN = 1.0
SIFT_SIGMA_MAX = 50.0
SIFT_MAX_ACCEL_FILES = 4096

# get_TOAs
TOAS_SUBINTS_MIN = 1
TOAS_SUBINTS_MAX = 4096
TOAS_SUBBANDS_MIN = 1
TOAS_SUBBANDS_MAX = 4096


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


def check_dm(dm: float) -> float:
    f = float(dm)
    if not (DM_MIN <= f <= DM_MAX):
        raise PolicyViolationError(f"DM {dm} outside [{DM_MIN}, {DM_MAX}]")
    return f


def check_dm_range(dm_low: float, dm_high: float) -> tuple[float, float]:
    lo = check_dm(dm_low)
    hi = check_dm(dm_high)
    if not (lo < hi):
        raise PolicyViolationError(f"dm_low ({lo}) must be < dm_high ({hi})")
    if (hi - lo) > DM_RANGE_MAX_SPAN:
        raise PolicyViolationError(
            f"DM range span ({hi - lo}) exceeds max allowed ({DM_RANGE_MAX_SPAN})"
        )
    return lo, hi


def check_dm_step(step: float) -> float:
    f = float(step)
    if not (DM_STEP_MIN <= f <= DM_STEP_MAX):
        raise PolicyViolationError(
            f"dm_step {step} outside [{DM_STEP_MIN}, {DM_STEP_MAX}]"
        )
    return f


def check_num_dms(n: int) -> int:
    if not isinstance(n, int) or isinstance(n, bool):
        raise PolicyViolationError(f"num_dms must be int, got {type(n).__name__}")
    if not (DM_NUM_MIN <= n <= DM_NUM_MAX):
        raise PolicyViolationError(f"num_dms {n} outside [{DM_NUM_MIN}, {DM_NUM_MAX}]")
    return n


def check_subband_count(n: int) -> int:
    if not isinstance(n, int) or isinstance(n, bool):
        raise PolicyViolationError(
            f"num_subbands must be int, got {type(n).__name__}"
        )
    if not (SUBBAND_MIN <= n <= SUBBAND_MAX):
        raise PolicyViolationError(
            f"num_subbands {n} outside [{SUBBAND_MIN}, {SUBBAND_MAX}]"
        )
    return n


def check_zmax(zmax: int) -> int:
    if not isinstance(zmax, int) or isinstance(zmax, bool):
        raise PolicyViolationError(f"zmax must be int, got {type(zmax).__name__}")
    if not (ACCELSEARCH_MIN_ZMAX <= zmax <= ACCELSEARCH_MAX_ZMAX):
        raise PolicyViolationError(
            f"zmax {zmax} outside [{ACCELSEARCH_MIN_ZMAX}, {ACCELSEARCH_MAX_ZMAX}]"
        )
    return zmax


def check_numharm(n: int) -> int:
    if not isinstance(n, int) or isinstance(n, bool):
        raise PolicyViolationError(f"numharm must be int, got {type(n).__name__}")
    if n not in ACCELSEARCH_VALID_NUMHARM:
        raise PolicyViolationError(
            f"numharm {n} must be one of {ACCELSEARCH_VALID_NUMHARM}"
        )
    return n


def check_sps_threshold(t: float) -> float:
    f = float(t)
    if not (SPS_MIN_THRESHOLD <= f <= SPS_MAX_THRESHOLD):
        raise PolicyViolationError(
            f"single_pulse_search threshold {t} outside "
            f"[{SPS_MIN_THRESHOLD}, {SPS_MAX_THRESHOLD}]"
        )
    return f


def check_sps_max_width_s(w: float) -> float:
    f = float(w)
    if not (SPS_MIN_WIDTH_S <= f <= SPS_MAX_WIDTH_S):
        raise PolicyViolationError(
            f"single_pulse_search max_width_s {w} outside "
            f"[{SPS_MIN_WIDTH_S}, {SPS_MAX_WIDTH_S}]"
        )
    return f


def check_sps_input_count(n: int) -> int:
    if not isinstance(n, int) or isinstance(n, bool):
        raise PolicyViolationError(f"input file count must be int, got {type(n).__name__}")
    if n < 1:
        raise PolicyViolationError("single_pulse_search requires at least one .dat file")
    if n > SPS_MAX_INPUT_FILES:
        raise PolicyViolationError(
            f"single_pulse_search input count {n} exceeds cap {SPS_MAX_INPUT_FILES}"
        )
    return n


def check_sift_min_num_dms(n: int) -> int:
    if not isinstance(n, int) or isinstance(n, bool):
        raise PolicyViolationError(f"min_num_dms must be int, got {type(n).__name__}")
    if not (SIFT_MIN_NUM_DMS_MIN <= n <= SIFT_MIN_NUM_DMS_MAX):
        raise PolicyViolationError(
            f"min_num_dms {n} outside [{SIFT_MIN_NUM_DMS_MIN}, {SIFT_MIN_NUM_DMS_MAX}]"
        )
    return n


def check_sift_low_dm_cutoff(v: float) -> float:
    f = float(v)
    if not (SIFT_LOW_DM_CUTOFF_MIN <= f <= SIFT_LOW_DM_CUTOFF_MAX):
        raise PolicyViolationError(
            f"low_dm_cutoff {v} outside [{SIFT_LOW_DM_CUTOFF_MIN}, {SIFT_LOW_DM_CUTOFF_MAX}]"
        )
    return f


def check_sift_sigma(v: float) -> float:
    f = float(v)
    if not (SIFT_SIGMA_MIN <= f <= SIFT_SIGMA_MAX):
        raise PolicyViolationError(
            f"sigma_threshold {v} outside [{SIFT_SIGMA_MIN}, {SIFT_SIGMA_MAX}]"
        )
    return f


def check_sift_accel_count(n: int) -> int:
    if not isinstance(n, int) or isinstance(n, bool):
        raise PolicyViolationError(f"accel file count must be int, got {type(n).__name__}")
    if n < 1:
        raise PolicyViolationError("sifting requires at least one .accel file")
    if n > SIFT_MAX_ACCEL_FILES:
        raise PolicyViolationError(
            f"sifting accel count {n} exceeds cap {SIFT_MAX_ACCEL_FILES}"
        )
    return n


def check_toas_subints(n: int) -> int:
    if not isinstance(n, int) or isinstance(n, bool):
        raise PolicyViolationError(f"num_subints must be int, got {type(n).__name__}")
    if not (TOAS_SUBINTS_MIN <= n <= TOAS_SUBINTS_MAX):
        raise PolicyViolationError(
            f"num_subints {n} outside [{TOAS_SUBINTS_MIN}, {TOAS_SUBINTS_MAX}]"
        )
    return n


def check_toas_subbands(n: int) -> int:
    if not isinstance(n, int) or isinstance(n, bool):
        raise PolicyViolationError(f"num_subbands must be int, got {type(n).__name__}")
    if not (TOAS_SUBBANDS_MIN <= n <= TOAS_SUBBANDS_MAX):
        raise PolicyViolationError(
            f"num_subbands {n} outside [{TOAS_SUBBANDS_MIN}, {TOAS_SUBBANDS_MAX}]"
        )
    return n


def check_ddplan_freq(freq_mhz: float) -> float:
    f = float(freq_mhz)
    if not (DDPLAN_FREQ_MIN_MHZ <= f <= DDPLAN_FREQ_MAX_MHZ):
        raise PolicyViolationError(
            f"freq_mhz {freq_mhz} outside [{DDPLAN_FREQ_MIN_MHZ}, {DDPLAN_FREQ_MAX_MHZ}]"
        )
    return f


def check_ddplan_bw(bw_mhz: float) -> float:
    f = float(bw_mhz)
    if not (DDPLAN_BW_MIN_MHZ <= f <= DDPLAN_BW_MAX_MHZ):
        raise PolicyViolationError(
            f"bw_mhz {bw_mhz} outside [{DDPLAN_BW_MIN_MHZ}, {DDPLAN_BW_MAX_MHZ}]"
        )
    return f


def check_ddplan_sample_time_us(t_us: float) -> float:
    f = float(t_us)
    if not (DDPLAN_SAMPLE_TIME_MIN_US <= f <= DDPLAN_SAMPLE_TIME_MAX_US):
        raise PolicyViolationError(
            f"sample_time_us {t_us} outside "
            f"[{DDPLAN_SAMPLE_TIME_MIN_US}, {DDPLAN_SAMPLE_TIME_MAX_US}]"
        )
    return f


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
