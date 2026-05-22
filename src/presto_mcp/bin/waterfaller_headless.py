#!/usr/bin/env python3
"""Run PRESTO waterfaller.py headlessly and save a PNG instead of plt.show().

Copied into each run's ``artifacts/`` by :mod:`presto_mcp.tools.waterfaller`.
Must be invoked inside the PRESTO Docker image (paths below are image-local).
"""

from __future__ import annotations

import glob
import os
import runpy
import shutil
import subprocess
import sys
from pathlib import Path

os.environ.setdefault("MPLBACKEND", "Agg")

import matplotlib

matplotlib.use("Agg", force=True)
import matplotlib.pyplot as plt

OUTPUT = os.environ.get("WATERFALL_OUTPUT", "waterfall.png")
_PSRFITS_EXTS = (".fits", ".sf", ".psrfits")


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


def _patch_psrfits_nchnoffs() -> None:
    """Best-effort hotfix for PRESTO psrfits NCHNOFFS type mismatch."""
    if os.environ.get("WATERFALLER_DISABLE_PSRFITS_PATCH", "").strip() == "1":
        return

    candidates: list[Path] = []
    for pattern in (
        "/usr/local/lib/python*/dist-packages/presto/psrfits.py",
        "/usr/lib/python*/dist-packages/presto/psrfits.py",
    ):
        candidates.extend(Path(p) for p in glob.glob(pattern))
    if not candidates:
        return

    needle = "if subint['NCHNOFFS'] > 0:"
    replacement = (
        "try:\n"
        "                nchnoffs = int(subint['NCHNOFFS'])\n"
        "            except Exception:\n"
        "                try:\n"
        "                    nchnoffs = int(float(str(subint['NCHNOFFS']).strip()))\n"
        "                except Exception:\n"
        "                    nchnoffs = 0\n"
        "            if nchnoffs > 0:"
    )

    for path in candidates:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "nchnoffs = int(subint['NCHNOFFS'])" in text:
            return  # already patched
        if needle not in text:
            continue
        try:
            path.write_text(text.replace(needle, replacement, 1), encoding="utf-8")
        except OSError as exc:
            print(f"[waterfaller_headless] psrfits hotfix write failed: {exc}", file=sys.stderr)
            return
        print(f"[waterfaller_headless] applied psrfits NCHNOFFS hotfix: {path}")
        return


def _maybe_convert_psrfits_input(argv: list[str]) -> list[str]:
    """Convert PSRFITS input to .fil to bypass known psrfits reader issues."""
    if not argv:
        return argv
    if os.environ.get("WATERFALLER_DISABLE_PSRFITS2FIL", "").strip() == "1":
        return argv

    input_path = argv[-1]
    if not input_path.lower().endswith(_PSRFITS_EXTS):
        return argv

    prefix = "/outputs/artifacts/waterfaller_input"
    cmd = ["psrfits2fil.py", "-o", prefix, input_path]
    try:
        proc = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except Exception as exc:  # pragma: no cover - defensive runtime fallback
        print(f"[waterfaller_headless] psrfits2fil launch failed: {exc}", file=sys.stderr)
        return argv

    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout).strip().splitlines()
        detail = tail[-1] if tail else "unknown error"
        print(
            f"[waterfaller_headless] psrfits2fil failed ({proc.returncode}): {detail}",
            file=sys.stderr,
        )
        return argv

    fil_hits = sorted(glob.glob(f"{prefix}*.fil"))
    if not fil_hits:
        print("[waterfaller_headless] psrfits2fil produced no .fil output", file=sys.stderr)
        return argv

    chosen = fil_hits[0]
    print(f"[waterfaller_headless] using converted filterbank: {chosen}")
    out = argv.copy()
    out[-1] = chosen
    return out


def _headless_show(*_args: object, **_kwargs: object) -> None:
    fig = plt.gcf()
    if fig.axes:
        fig.savefig(OUTPUT, dpi=150, bbox_inches="tight")
    plt.close("all")


plt.show = _headless_show  # type: ignore[method-assign]

if __name__ == "__main__":
    _patch_psrfits_nchnoffs()
    tool_argv = _maybe_convert_psrfits_input(sys.argv[1:])
    sys.argv = [PRESTO_WATERFALLER, *tool_argv]
    runpy.run_path(PRESTO_WATERFALLER, run_name="__main__")
