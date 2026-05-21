#!/usr/bin/env python3
"""Run PRESTO waterfaller.py headlessly and save a PNG instead of plt.show().

Copied into each run's ``artifacts/`` by :mod:`presto_mcp.tools.waterfaller`.
Must be invoked inside the PRESTO Docker image (paths below are image-local).
"""

from __future__ import annotations

import os
import runpy
import shutil
import sys
from pathlib import Path

os.environ.setdefault("MPLBACKEND", "Agg")

import matplotlib

matplotlib.use("Agg", force=True)
import matplotlib.pyplot as plt

OUTPUT = os.environ.get("WATERFALL_OUTPUT", "waterfall.png")


def _resolve_waterfaller_script() -> str:
    """Locate upstream ``waterfaller.py`` inside the PRESTO image."""
    override = os.environ.get("PRESTO_WATERFALLER_SCRIPT", "").strip()
    if override:
        return override
    found = shutil.which("waterfaller.py")
    if found:
        return found
    for candidate in (
        "/software/presto5/installation/bin/waterfaller.py",
        "/usr/local/bin/waterfaller.py",
    ):
        if Path(candidate).is_file():
            return candidate
    return "/software/presto5/installation/bin/waterfaller.py"


PRESTO_WATERFALLER = _resolve_waterfaller_script()


def _headless_show(*_args: object, **_kwargs: object) -> None:
    fig = plt.gcf()
    if fig.axes:
        fig.savefig(OUTPUT, dpi=150, bbox_inches="tight")
    plt.close("all")


plt.show = _headless_show  # type: ignore[method-assign]

if __name__ == "__main__":
    sys.argv = [PRESTO_WATERFALLER, *sys.argv[1:]]
    runpy.run_path(PRESTO_WATERFALLER, run_name="__main__")
