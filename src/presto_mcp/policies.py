"""Numeric policy guards applied before invoking PRESTO.

Each ``check_*`` raises :class:`PolicyViolationError` on a bad value and returns
the clamped/coerced value on success. Keep these dumb and explicit — no
``isinstance`` ladders, no clever defaults.
"""

from __future__ import annotations

import re

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
ACCELSEARCH_MIN_WMAX = 0
ACCELSEARCH_MAX_WMAX = 1200
ACCELSEARCH_SIGMA_MIN = 1.0
ACCELSEARCH_SIGMA_MAX = 30.0
ACCELSEARCH_NCPUS_MIN = 1
ACCELSEARCH_NCPUS_MAX = 64
ACCELSEARCH_CAND_LIMIT_MIN = 1
ACCELSEARCH_CAND_LIMIT_MAX = 1000

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

# zapbirds
ZAPBIRDS_MIN_NFFT = 0
ZAPBIRDS_MAX_NFFT = 1 << 30
ZAPBIRDS_BARYV_MIN = -0.1
ZAPBIRDS_BARYV_MAX = 0.1

# rrattrap
RRATTRAP_MIN_SP_FILES = 1
RRATTRAP_MAX_SP_FILES = 4096

# make_spd
MAKESPD_MIN_SP_FILES = 1
MAKESPD_MAX_SP_FILES = 4096

# waterfaller
WATERFALL_MIN_DURATION_S = 1e-6
WATERFALL_MAX_DURATION_S = 600.0
WATERFALL_MIN_START_S = 0.0
WATERFALL_MAX_START_S = 1e6

# get_TOAs
TOAS_SUBINTS_MIN = 1
TOAS_SUBINTS_MAX = 4096
TOAS_SUBBANDS_MIN = 1
TOAS_SUBBANDS_MAX = 4096
TOAS_GAUSSIAN_WIDTH_MIN = 1e-6
TOAS_GAUSSIAN_WIDTH_MAX = 1.0


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


def check_accelsearch_wmax(w: int | None) -> int | None:
    if w is None:
        return None
    if not isinstance(w, int) or isinstance(w, bool):
        raise PolicyViolationError(f"wmax must be int, got {type(w).__name__}")
    if not (ACCELSEARCH_MIN_WMAX <= w <= ACCELSEARCH_MAX_WMAX):
        raise PolicyViolationError(
            f"wmax {w} outside [{ACCELSEARCH_MIN_WMAX}, {ACCELSEARCH_MAX_WMAX}]"
        )
    return w


def check_accelsearch_sigma(v: float | None) -> float | None:
    if v is None:
        return None
    f = float(v)
    if not (ACCELSEARCH_SIGMA_MIN <= f <= ACCELSEARCH_SIGMA_MAX):
        raise PolicyViolationError(
            f"sigma {v} outside [{ACCELSEARCH_SIGMA_MIN}, {ACCELSEARCH_SIGMA_MAX}]"
        )
    return f


def check_accelsearch_ncpus(n: int | None) -> int | None:
    if n is None:
        return None
    if not isinstance(n, int) or isinstance(n, bool):
        raise PolicyViolationError(f"ncpus must be int, got {type(n).__name__}")
    if not (ACCELSEARCH_NCPUS_MIN <= n <= ACCELSEARCH_NCPUS_MAX):
        raise PolicyViolationError(
            f"ncpus {n} outside [{ACCELSEARCH_NCPUS_MIN}, {ACCELSEARCH_NCPUS_MAX}]"
        )
    return n


def check_accelsearch_candidate_limit(n: int | None) -> int | None:
    if n is None:
        return None
    if not isinstance(n, int) or isinstance(n, bool):
        raise PolicyViolationError(
            f"candidate_limit must be int, got {type(n).__name__}"
        )
    if not (ACCELSEARCH_CAND_LIMIT_MIN <= n <= ACCELSEARCH_CAND_LIMIT_MAX):
        raise PolicyViolationError(
            f"candidate_limit {n} outside "
            f"[{ACCELSEARCH_CAND_LIMIT_MIN}, {ACCELSEARCH_CAND_LIMIT_MAX}]"
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


def check_toas_gaussian_width(width: float | None) -> float | None:
    if width is None:
        return None
    f = float(width)
    if not (TOAS_GAUSSIAN_WIDTH_MIN <= f <= TOAS_GAUSSIAN_WIDTH_MAX):
        raise PolicyViolationError(
            f"gaussian_width {width} outside "
            f"[{TOAS_GAUSSIAN_WIDTH_MIN}, {TOAS_GAUSSIAN_WIDTH_MAX}]"
        )
    return f


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


def check_zapbirds_baryv(v: float | None) -> float | None:
    if v is None:
        return None
    f = float(v)
    if not (ZAPBIRDS_BARYV_MIN <= f <= ZAPBIRDS_BARYV_MAX):
        raise PolicyViolationError(
            f"baryv {v} outside [{ZAPBIRDS_BARYV_MIN}, {ZAPBIRDS_BARYV_MAX}]"
        )
    return f


def check_zapbirds_nfft(n: int | None) -> int | None:
    if n is None:
        return None
    if not isinstance(n, int) or isinstance(n, bool):
        raise PolicyViolationError(f"nfft must be int, got {type(n).__name__}")
    if not (ZAPBIRDS_MIN_NFFT <= n <= ZAPBIRDS_MAX_NFFT):
        raise PolicyViolationError(
            f"nfft {n} outside [{ZAPBIRDS_MIN_NFFT}, {ZAPBIRDS_MAX_NFFT}]"
        )
    return n


def check_rrattrap_input_count(n: int) -> int:
    if not isinstance(n, int) or isinstance(n, bool):
        raise PolicyViolationError(f"input count must be int, got {type(n).__name__}")
    if n < RRATTRAP_MIN_SP_FILES:
        raise PolicyViolationError("rrattrap requires at least one .singlepulse file")
    if n > RRATTRAP_MAX_SP_FILES:
        raise PolicyViolationError(
            f"rrattrap input count {n} exceeds cap {RRATTRAP_MAX_SP_FILES}"
        )
    return n


def check_makespd_input_count(n: int) -> int:
    if not isinstance(n, int) or isinstance(n, bool):
        raise PolicyViolationError(f"input count must be int, got {type(n).__name__}")
    if n < MAKESPD_MIN_SP_FILES:
        raise PolicyViolationError("make_spd requires at least one .singlepulse file")
    if n > MAKESPD_MAX_SP_FILES:
        raise PolicyViolationError(
            f"make_spd input count {n} exceeds cap {MAKESPD_MAX_SP_FILES}"
        )
    return n


def check_waterfall_duration(d: float) -> float:
    f = float(d)
    if not (WATERFALL_MIN_DURATION_S <= f <= WATERFALL_MAX_DURATION_S):
        raise PolicyViolationError(
            f"duration_s {d} outside "
            f"[{WATERFALL_MIN_DURATION_S}, {WATERFALL_MAX_DURATION_S}]"
        )
    return f


def check_waterfall_start(t: float) -> float:
    f = float(t)
    if not (WATERFALL_MIN_START_S <= f <= WATERFALL_MAX_START_S):
        raise PolicyViolationError(
            f"start_s {t} outside "
            f"[{WATERFALL_MIN_START_S}, {WATERFALL_MAX_START_S}]"
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


# -- data prep / RFI / fold QC / advanced ------------------------------------

DOWNSAMPLE_FACTOR_MIN = 2
DOWNSAMPLE_FACTOR_MAX = 1024

TRUNCATE_START_SAMPLE_MIN = 0
TRUNCATE_START_SAMPLE_MAX = 10**12
TRUNCATE_NUM_SAMPLES_MIN = 1
TRUNCATE_NUM_SAMPLES_MAX = 10**10
TRUNCATE_START_S_MIN = 0.0
TRUNCATE_START_S_MAX = 86_400.0
TRUNCATE_DURATION_S_MIN = 1e-6
TRUNCATE_DURATION_S_MAX = 86_400.0

PROFILE_FILE_COUNT_MIN = 1
PROFILE_FILE_COUNT_MAX = 4096

FREQUENCY_HZ_MIN = 1e-9
FREQUENCY_HZ_MAX = 1e9

PFDZAP_TOKEN_MAX = 512
_PFDZAP_TOKEN_RE = re.compile(r"^\d+:\d+$")

SEARCH_BIN_FREQ_MIN_HZ = 0.0
SEARCH_BIN_FREQ_MAX_HZ = 5.0e5


def check_downsample_factor(n: int) -> int:
    if not isinstance(n, int) or isinstance(n, bool):
        raise PolicyViolationError(f"downsample factor must be int, got {type(n).__name__}")
    if not (DOWNSAMPLE_FACTOR_MIN <= n <= DOWNSAMPLE_FACTOR_MAX):
        raise PolicyViolationError(
            f"downsample factor {n} outside "
            f"[{DOWNSAMPLE_FACTOR_MIN}, {DOWNSAMPLE_FACTOR_MAX}]"
        )
    return n


def check_truncate_start_sample(n: int) -> int:
    if not isinstance(n, int) or isinstance(n, bool):
        raise PolicyViolationError(f"start_sample must be int, got {type(n).__name__}")
    if not (TRUNCATE_START_SAMPLE_MIN <= n <= TRUNCATE_START_SAMPLE_MAX):
        raise PolicyViolationError(
            f"start_sample {n} outside "
            f"[{TRUNCATE_START_SAMPLE_MIN}, {TRUNCATE_START_SAMPLE_MAX}]"
        )
    return n


def check_truncate_num_samples(n: int) -> int:
    if not isinstance(n, int) or isinstance(n, bool):
        raise PolicyViolationError(f"num_samples must be int, got {type(n).__name__}")
    if not (TRUNCATE_NUM_SAMPLES_MIN <= n <= TRUNCATE_NUM_SAMPLES_MAX):
        raise PolicyViolationError(
            f"num_samples {n} outside "
            f"[{TRUNCATE_NUM_SAMPLES_MIN}, {TRUNCATE_NUM_SAMPLES_MAX}]"
        )
    return n


def check_truncate_start_s(s: float) -> float:
    f = float(s)
    if not (TRUNCATE_START_S_MIN <= f <= TRUNCATE_START_S_MAX):
        raise PolicyViolationError(
            f"start_s {s} outside [{TRUNCATE_START_S_MIN}, {TRUNCATE_START_S_MAX}]"
        )
    return f


def check_truncate_duration_s(s: float) -> float:
    f = float(s)
    if not (TRUNCATE_DURATION_S_MIN <= f <= TRUNCATE_DURATION_S_MAX):
        raise PolicyViolationError(
            f"duration_s {s} outside "
            f"[{TRUNCATE_DURATION_S_MIN}, {TRUNCATE_DURATION_S_MAX}]"
        )
    return f


def check_profile_file_count(files: list[str]) -> list[str]:
    if not isinstance(files, list):
        raise PolicyViolationError(
            f"profile_files must be list, got {type(files).__name__}"
        )
    n = len(files)
    if n < PROFILE_FILE_COUNT_MIN:
        raise PolicyViolationError("sum_profiles requires at least one profile file")
    if n > PROFILE_FILE_COUNT_MAX:
        raise PolicyViolationError(
            f"sum_profiles input count {n} exceeds cap {PROFILE_FILE_COUNT_MAX}"
        )
    return files


def check_frequency_hz(f_hz: float) -> float:
    f = float(f_hz)
    if not (FREQUENCY_HZ_MIN <= f <= FREQUENCY_HZ_MAX):
        raise PolicyViolationError(
            f"frequency_hz {f_hz} outside [{FREQUENCY_HZ_MIN}, {FREQUENCY_HZ_MAX}]"
        )
    return f


def check_fourier_fold_period_or_freq(
    period_s: float | None, frequency_hz: float | None
) -> tuple[float | None, float | None]:
    """Exactly one of (period_s, frequency_hz) must be set; both validated."""
    if (period_s is None) == (frequency_hz is None):
        raise PolicyViolationError(
            "fourier_fold requires exactly one of period_s or frequency_hz"
        )
    p = check_prepfold_period(period_s) if period_s is not None else None
    f = check_frequency_hz(frequency_hz) if frequency_hz is not None else None
    return p, f


def check_pfdzap_commands(cmds: list[str] | None) -> list[str] | None:
    if cmds is None:
        return None
    if not isinstance(cmds, list):
        raise PolicyViolationError(
            f"zap_commands must be list[str], got {type(cmds).__name__}"
        )
    if len(cmds) > PFDZAP_TOKEN_MAX:
        raise PolicyViolationError(
            f"pfdzap commands ({len(cmds)}) exceed cap {PFDZAP_TOKEN_MAX}"
        )
    bad: list[str] = []
    for c in cmds:
        if not isinstance(c, str) or not _PFDZAP_TOKEN_RE.match(c):
            bad.append(repr(c))
    if bad:
        raise PolicyViolationError(
            f"pfdzap commands must match '<low>:<high>'; bad tokens: {bad[:5]}"
        )
    return cmds


# -- stacksearch / simple_zapbirds / compare_periods --------------------------

STACKSEARCH_MIN_FFT = 2
STACKSEARCH_MAX_FFT = 256
SIMPLE_ZAPBIRDS_MAX_FFT = 256

PERIOD_MS_MIN = 1e-3
PERIOD_MS_MAX = 1.0e8  # 100 s
COMPARE_TOLERANCE_MIN = 1e-9
COMPARE_TOLERANCE_MAX = 0.5
COMPARE_MAX_HARMONIC_MIN = 1
COMPARE_MAX_HARMONIC_MAX = 64
PAR_FILE_COUNT_MIN = 1
PAR_FILE_COUNT_MAX = 256


def check_stacksearch_input_count(n: int) -> int:
    if not isinstance(n, int) or isinstance(n, bool):
        raise PolicyViolationError(f"fft file count must be int, got {type(n).__name__}")
    if n < STACKSEARCH_MIN_FFT:
        raise PolicyViolationError(
            f"stacksearch requires at least {STACKSEARCH_MIN_FFT} .fft files"
        )
    if n > STACKSEARCH_MAX_FFT:
        raise PolicyViolationError(
            f"stacksearch input count {n} exceeds cap {STACKSEARCH_MAX_FFT}"
        )
    return n


def check_simple_zapbirds_input_count(n: int) -> int:
    if not isinstance(n, int) or isinstance(n, bool):
        raise PolicyViolationError(f"fft file count must be int, got {type(n).__name__}")
    if n < 1:
        raise PolicyViolationError("simple_zapbirds requires at least one .fft file")
    if n > SIMPLE_ZAPBIRDS_MAX_FFT:
        raise PolicyViolationError(
            f"simple_zapbirds input count {n} exceeds cap {SIMPLE_ZAPBIRDS_MAX_FFT}"
        )
    return n


def check_period_ms(period_ms: float) -> float:
    f = float(period_ms)
    if not (PERIOD_MS_MIN <= f <= PERIOD_MS_MAX):
        raise PolicyViolationError(
            f"period_ms {period_ms} outside [{PERIOD_MS_MIN}, {PERIOD_MS_MAX}]"
        )
    return f


def check_compare_tolerance(tol: float | None) -> float:
    if tol is None:
        return 1e-3
    f = float(tol)
    if not (COMPARE_TOLERANCE_MIN <= f <= COMPARE_TOLERANCE_MAX):
        raise PolicyViolationError(
            f"tolerance {tol} outside [{COMPARE_TOLERANCE_MIN}, {COMPARE_TOLERANCE_MAX}]"
        )
    return f


def check_compare_max_harmonic(n: int | None) -> int:
    if n is None:
        return 8
    if not isinstance(n, int) or isinstance(n, bool):
        raise PolicyViolationError(f"max_harmonic must be int, got {type(n).__name__}")
    if not (COMPARE_MAX_HARMONIC_MIN <= n <= COMPARE_MAX_HARMONIC_MAX):
        raise PolicyViolationError(
            f"max_harmonic {n} outside "
            f"[{COMPARE_MAX_HARMONIC_MIN}, {COMPARE_MAX_HARMONIC_MAX}]"
        )
    return n


def check_par_file_count(files: list[str]) -> list[str]:
    if not isinstance(files, list):
        raise PolicyViolationError(f"par_files must be list, got {type(files).__name__}")
    n = len(files)
    if n < PAR_FILE_COUNT_MIN:
        raise PolicyViolationError("compare_periods requires at least one .par file")
    if n > PAR_FILE_COUNT_MAX:
        raise PolicyViolationError(
            f"par_files count {n} exceeds cap {PAR_FILE_COUNT_MAX}"
        )
    return files


def check_search_bin_freq_range(
    low_hz: float | None, high_hz: float | None
) -> tuple[float | None, float | None]:
    """Optional band; if both provided, validate ordering + range."""
    if low_hz is None and high_hz is None:
        return None, None
    if low_hz is None or high_hz is None:
        raise PolicyViolationError("search_bin band requires both low_hz and high_hz")
    lo = float(low_hz)
    hi = float(high_hz)
    if not (SEARCH_BIN_FREQ_MIN_HZ <= lo < hi <= SEARCH_BIN_FREQ_MAX_HZ):
        raise PolicyViolationError(
            f"search_bin band [{lo}, {hi}] invalid; require "
            f"{SEARCH_BIN_FREQ_MIN_HZ} <= low < high <= {SEARCH_BIN_FREQ_MAX_HZ}"
        )
    return lo, hi
