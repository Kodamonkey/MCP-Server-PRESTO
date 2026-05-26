#!/usr/bin/env python3
"""Run PRESTO waterfaller.py headlessly and save a PNG instead of plt.show().

Copied into each run's ``artifacts/`` by :mod:`presto_mcp.tools.waterfaller`.
Must be invoked inside the PRESTO Docker image (paths below are image-local).
"""

from __future__ import annotations

import glob
import json
import os
import runpy
import shutil
import subprocess
import sys
from pathlib import Path

os.environ.setdefault("MPLBACKEND", "Agg")

import matplotlib

matplotlib.use("Agg", force=True)
import matplotlib.cm as cm
import matplotlib.pyplot as plt
from matplotlib.backend_bases import FigureCanvasBase

OUTPUT = os.environ.get("WATERFALL_OUTPUT", "waterfall.png")
_PSRFITS_EXTS = (".fits", ".sf", ".psrfits")
_COMPAT_NOTES_PATH = "/outputs/artifacts/waterfaller_compat.json"
_compat_notes: dict[str, object] = {
    "compat_mode": False,
    "psrfits_hotfix_applied": False,
    "psrfits2fil_converted": False,
    "converted_input_path": None,
}


def _write_compat_notes() -> None:
    try:
        with open(_COMPAT_NOTES_PATH, "w", encoding="utf-8") as fh:
            json.dump(_compat_notes, fh, indent=2, sort_keys=True)
    except OSError as exc:
        print(f"[waterfaller_headless] compat notes write failed: {exc}", file=sys.stderr)


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
        _compat_notes["psrfits_hotfix_applied"] = True
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
    _compat_notes["psrfits2fil_converted"] = True
    _compat_notes["converted_input_path"] = chosen
    out = argv.copy()
    out[-1] = chosen
    return out


def _headless_show(*_args: object, **_kwargs: object) -> None:
    fig = plt.gcf()
    if fig.axes:
        fig.savefig(OUTPUT, dpi=150, bbox_inches="tight")
    plt.close("all")


plt.show = _headless_show  # type: ignore[method-assign]


def _patch_canvas_window_title() -> None:
    """Compat shim for Agg/no-window backends."""
    if hasattr(FigureCanvasBase, "set_window_title"):
        return

    def _no_window_title(self: FigureCanvasBase, _title: str) -> None:
        return

    FigureCanvasBase.set_window_title = _no_window_title  # type: ignore[attr-defined]


def _patch_matplotlib_cmap_compat() -> None:
    """Compat shim for older PRESTO code expecting ``matplotlib.cm.cmap_d``."""
    if hasattr(cm, "cmap_d"):
        return
    cmap_d: dict[str, object] = {}
    # ``plt.colormaps`` exists in modern matplotlib and returns all registered maps.
    for name in plt.colormaps():
        try:
            cmap_d[name] = matplotlib.colormaps[name]
        except Exception:
            continue
    cm.cmap_d = cmap_d  # type: ignore[attr-defined]


if __name__ == "__main__":
    # Default: preserve original PRESTO waterfaller behavior.
    # Opt-in compat mode keeps historical MCP fallbacks.
    compat_mode = os.environ.get("WATERFALLER_ENABLE_COMPAT_PATCHES", "").strip() == "1"
    _compat_notes["compat_mode"] = compat_mode
    if compat_mode:
        _patch_psrfits_nchnoffs()
    _patch_canvas_window_title()
    _patch_matplotlib_cmap_compat()
    tool_argv = _maybe_convert_psrfits_input(sys.argv[1:]) if compat_mode else sys.argv[1:]
    _write_compat_notes()
    sys.argv = [PRESTO_WATERFALLER, *tool_argv]
    runpy.run_path(PRESTO_WATERFALLER, run_name="__main__")
