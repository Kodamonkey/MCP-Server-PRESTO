#!/usr/bin/env python3
"""Run PRESTO waterfaller.py headlessly and save a PNG instead of plt.show().

Copied into each run's ``artifacts/`` by :mod:`presto_mcp.tools.waterfaller`.
Must be invoked inside the PRESTO Docker image (paths below are image-local).
"""

from __future__ import annotations

import os
import runpy
import sys

os.environ.setdefault("MPLBACKEND", "Agg")

import matplotlib

matplotlib.use("Agg", force=True)
import matplotlib.pyplot as plt

OUTPUT = os.environ.get("WATERFALL_OUTPUT", "waterfall.png")
PRESTO_WATERFALLER = "/software/presto5/installation/bin/waterfaller.py"


def _headless_show(*_args: object, **_kwargs: object) -> None:
    fig = plt.gcf()
    if fig.axes:
        fig.savefig(OUTPUT, dpi=150, bbox_inches="tight")
    plt.close("all")


plt.show = _headless_show  # type: ignore[method-assign]

if __name__ == "__main__":
    sys.argv = [PRESTO_WATERFALLER, *sys.argv[1:]]
    runpy.run_path(PRESTO_WATERFALLER, run_name="__main__")
