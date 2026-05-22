"""Collect, convert and publish PNG visual diagnostics + thumbnails.

PRESTO writes plots as raster (``.png``) and PostScript (``.ps`` / ``.eps``).
This builder:

  * copies raster images into ``outputs/<run_id>/visuals/``,
  * converts ``.ps`` / ``.eps`` to PNG **when Ghostscript is available**,
    registering a warning (never failing the run) when it is not,
  * generates small thumbnails into ``outputs/<run_id>/thumbnails/``.

``.ps`` / ``.eps`` files are only ever used as conversion *sources*; they are
never published to the public tree.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from .artifact_manager import ArtifactManager
from .schemas import Artifact, ReportArtifactKind

log = logging.getLogger("presto_mcp.reporting.visual_builder")


def _mkstemp_path(prefix: str) -> Path:
    """Create a temp PNG path with the OS file descriptor closed (Windows-safe)."""
    fd, name = tempfile.mkstemp(suffix=".png", prefix=prefix)
    os.close(fd)
    return Path(name)

_RASTER_EXT = {".png", ".jpg", ".jpeg"}
_VECTOR_EXT = {".ps", ".eps"}
_THUMB_SIZE = (480, 480)
_GS_CANDIDATES = ("gs", "gswin64c", "gswin32c")
_GS_TIMEOUT_S = 90


def find_ghostscript() -> str | None:
    """Return a Ghostscript executable on PATH, or ``None``."""
    for name in _GS_CANDIDATES:
        found = shutil.which(name)
        if found:
            return found
    return None


def collect_visuals(
    roots: list[Path],
    am: ArtifactManager,
    *,
    make_thumbnails: bool,
    created_by_tool: str = "generate_visual_artifacts",
) -> tuple[list[Artifact], list[Artifact]]:
    """Publish visuals (and optionally thumbnails); return ``(visuals, thumbs)``."""
    visuals: list[Artifact] = []
    thumbs: list[Artifact] = []
    used_names: set[str] = set()
    gs_bin: str | None = None
    gs_probed = False

    raster: list[Path] = []
    vector: list[Path] = []
    for root in roots:
        root = Path(root)
        if not root.is_dir():
            continue
        for p in sorted(root.rglob("*")):
            if not p.is_file():
                continue
            ext = p.suffix.lower()
            if ext in _RASTER_EXT:
                raster.append(p)
            elif ext in _VECTOR_EXT:
                vector.append(p)

    for src in raster:
        dest_name = _unique_name(src.name, ".png", used_names)
        try:
            art = am.publish_file(
                src,
                ReportArtifactKind.VISUAL_PNG,
                f"visuals/{dest_name}",
                created_by_tool=created_by_tool,
                description="PRESTO diagnostic plot",
            )
        except Exception as e:  # noqa: BLE001
            am.add_warning(f"could not publish visual {src.name}: {e}")
            continue
        visuals.append(art)

    for src in vector:
        if not gs_probed:
            gs_bin = find_ghostscript()
            gs_probed = True
            if gs_bin is None:
                am.add_warning(
                    "Ghostscript not found; .ps/.eps plots were not converted to PNG. "
                    "Install Ghostscript to include PostScript diagnostics."
                )
        if gs_bin is None:
            continue
        png = _convert_postscript(gs_bin, src, am)
        if png is None:
            continue
        dest_name = _unique_name(src.stem + ".png", ".png", used_names)
        try:
            art = am.publish_file(
                png,
                ReportArtifactKind.VISUAL_PNG,
                f"visuals/{dest_name}",
                source_file=str(src),
                created_by_tool=created_by_tool,
                description="PRESTO PostScript plot converted to PNG",
            )
        finally:
            png.unlink(missing_ok=True)
        visuals.append(art)

    if make_thumbnails:
        for art in visuals:
            thumb = _make_thumbnail(am, art, created_by_tool)
            if thumb is not None:
                thumbs.append(thumb)

    return visuals, thumbs


def _convert_postscript(gs_bin: str, src: Path, am: ArtifactManager) -> Path | None:
    """Convert one ``.ps`` / ``.eps`` to a temp PNG; ``None`` on failure."""
    out = _mkstemp_path("presto_vis_")
    argv = [
        gs_bin,
        "-q",
        "-dSAFER",
        "-dBATCH",
        "-dNOPAUSE",
        "-sDEVICE=png16m",
        "-r150",
    ]
    if src.suffix.lower() == ".eps":
        argv.append("-dEPSCrop")
    argv += [f"-sOutputFile={out}", str(src)]
    try:
        proc = subprocess.run(  # noqa: S603 - argv list, shell=False
            argv,
            capture_output=True,
            timeout=_GS_TIMEOUT_S,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        am.add_warning(f"Ghostscript conversion failed for {src.name}: {e}")
        out.unlink(missing_ok=True)
        return None
    if proc.returncode != 0 or not out.is_file() or out.stat().st_size == 0:
        am.add_warning(
            f"Ghostscript could not convert {src.name} (exit {proc.returncode})"
        )
        out.unlink(missing_ok=True)
        return None
    return out


def _make_thumbnail(
    am: ArtifactManager, visual: Artifact, created_by_tool: str
) -> Artifact | None:
    src = am.run_dir / visual.path
    if not src.is_file():
        return None
    tmp = _mkstemp_path("presto_thumb_")
    try:
        with Image.open(src) as im:
            im = im.convert("RGB")
            im.thumbnail(_THUMB_SIZE)
            im.save(tmp, "PNG")
    except (UnidentifiedImageError, OSError) as e:
        am.add_warning(f"could not thumbnail {visual.path}: {e}")
        tmp.unlink(missing_ok=True)
        return None
    name = Path(visual.path).name
    try:
        return am.publish_file(
            tmp,
            ReportArtifactKind.THUMBNAIL,
            f"thumbnails/{name}",
            source_file=visual.path,
            created_by_tool=created_by_tool,
            description="thumbnail preview",
        )
    except Exception as e:  # noqa: BLE001
        am.add_warning(f"could not publish thumbnail for {visual.path}: {e}")
        return None
    finally:
        tmp.unlink(missing_ok=True)


def _unique_name(name: str, suffix: str, used: set[str]) -> str:
    base = Path(name).stem
    candidate = f"{base}{suffix}"
    i = 1
    while candidate in used:
        i += 1
        candidate = f"{base}_{i}{suffix}"
    used.add(candidate)
    return candidate


__all__ = ["collect_visuals", "find_ghostscript"]
