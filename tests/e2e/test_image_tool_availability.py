"""Smoke-test PRESTO command availability in the configured Docker image."""

from __future__ import annotations

import shutil
import subprocess

import pytest

from presto_mcp.config import get_settings

pytestmark = pytest.mark.e2e


EXPOSED_COMMANDS = (
    "readfile",
    "rfifind",
    "prepfold",
    "prepdata",
    "DDplan.py",
    "prepsubband",
    "realfft",
    "accelsearch",
    "single_pulse_search.py",
    "/software/presto5/examplescripts/ACCEL_sift.py",
    "get_TOAs.py",
    "zapbirds",
    "rrattrap.py",
    "make_spd.py",
    "plot_spd.py",
    "waterfaller.py",
    "psrfits2fil.py",
    "downsample_filterbank.py",
    "fb_truncate.py",
    "rfifind_stats.py",
    "pfd2png.sh",
    "makezaplist.py",
    "weights_to_ignorechan.py",
    "sum_profiles.py",
    "search_bin",
)


def test_exposed_presto_commands_exist_in_image() -> None:
    docker = shutil.which("docker")
    if docker is None:
        pytest.skip("docker not available")

    s = get_settings()
    script = "set -eu; " + "; ".join(f"command -v {cmd}" for cmd in EXPOSED_COMMANDS)
    cp = subprocess.run(
        [docker, "run", "--rm", "--network=none", s.image, "sh", "-lc", script],
        shell=False,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert cp.returncode == 0, cp.stderr or cp.stdout
