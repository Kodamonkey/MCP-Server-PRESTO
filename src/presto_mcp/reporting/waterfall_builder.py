"""Generate per-candidate waterfall diagnostics (PNG / PDF).

Rendering is delegated to an injected ``waterfall_fn`` — in production this is
the existing containerized ``presto.waterfaller`` tool, so no host-side plotting
dependency is added and the sandbox model is preserved. The builder owns
candidate selection, filtering, the ``max_candidates_for_waterfalls`` cap,
publication into the public tree and PNG->PDF conversion (via Pillow).

Per-candidate failures are recorded as warnings and never abort the run.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from .artifact_manager import ArtifactManager
from .schemas import Artifact, ArtifactPolicy, Candidate, ReportArtifactKind, ReportOptions

log = logging.getLogger("presto_mcp.reporting.waterfall_builder")

# (input_file, start_s, duration_s, dm, cmap, candidate_id) -> host PNG path | None
WaterfallFn = Callable[..., Path | None]

CandidateSelection = str  # "one" | "top_n" | "all"


def generate_waterfalls(
    candidates: list[Candidate],
    am: ArtifactManager,
    *,
    policy: ArtifactPolicy,
    options: ReportOptions,
    waterfall_fn: WaterfallFn,
    input_file: str,
    selection: CandidateSelection = "top_n",
    top_n: int = 10,
    candidate_id: str | None = None,
    min_snr: float | None = None,
    min_dm: float | None = None,
    max_dm: float | None = None,
    time_window_sec: float | None = None,
    export_png: bool = True,
    export_pdf: bool = False,
    created_by_tool: str = "generate_candidate_waterfalls",
) -> list[Artifact]:
    """Render, publish and return waterfall artifacts for selected candidates."""
    window = time_window_sec or options.waterfall_window_sec
    cmap = options.waterfall_cmap or policy.default_waterfall_cmap

    eligible = _select(
        candidates,
        selection=selection,
        top_n=top_n,
        candidate_id=candidate_id,
        min_snr=min_snr,
        min_dm=min_dm,
        max_dm=max_dm,
        am=am,
    )

    cap = max(0, policy.max_candidates_for_waterfalls)
    if len(eligible) > cap:
        am.add_warning(
            f"waterfall candidate count {len(eligible)} exceeds "
            f"max_candidates_for_waterfalls={cap}; truncated to {cap}"
        )
        eligible = eligible[:cap]

    artifacts: list[Artifact] = []
    backend_failed_once = False
    for cand in eligible:
        if backend_failed_once:
            am.add_warning(
                f"candidate {cand.candidate_id}: skipped after prior backend failure"
            )
            continue
        if cand.dm is None or cand.time_sec is None:
            am.add_warning(
                f"candidate {cand.candidate_id}: missing dm/time, cannot render waterfall"
            )
            continue
        start = max(0.0, cand.time_sec - window / 2.0)
        try:
            png = waterfall_fn(
                input_file=input_file,
                start_s=start,
                duration_s=window,
                dm=cand.dm,
                cmap=cmap,
                candidate_id=cand.candidate_id,
            )
        except Exception as e:  # noqa: BLE001 - one candidate must not abort the run
            am.add_warning(f"candidate {cand.candidate_id}: waterfall render failed: {e}")
            log.warning("waterfall render failed for %s", cand.candidate_id, exc_info=True)
            if "waterfaller backend failed" in str(e):
                backend_failed_once = True
            continue
        if png is None or not Path(png).is_file():
            am.add_warning(
                f"candidate {cand.candidate_id}: waterfall backend produced no image"
            )
            continue
        artifacts.extend(
            _publish_candidate_waterfall(
                am,
                cand,
                Path(png),
                export_png=export_png,
                export_pdf=export_pdf,
                created_by_tool=created_by_tool,
            )
        )
    return artifacts


def _publish_candidate_waterfall(
    am: ArtifactManager,
    cand: Candidate,
    png: Path,
    *,
    export_png: bool,
    export_pdf: bool,
    created_by_tool: str,
) -> list[Artifact]:
    out: list[Artifact] = []
    cid = cand.candidate_id

    if export_png:
        try:
            top = am.publish_file(
                png,
                ReportArtifactKind.WATERFALL_PNG,
                f"waterfalls/{cid}.png",
                created_by_tool=created_by_tool,
                candidate_id=cid,
                description="per-candidate waterfall",
            )
            am.publish_file(
                png,
                ReportArtifactKind.WATERFALL_PNG,
                f"candidates/{cid}/waterfall.png",
                created_by_tool=created_by_tool,
                candidate_id=cid,
                description="per-candidate waterfall",
            )
            cand.paths.waterfall_png_path = top.path
            out.append(top)
        except Exception as e:  # noqa: BLE001
            am.add_warning(f"candidate {cid}: could not publish waterfall PNG: {e}")

    if export_pdf:
        pdf = _png_to_pdf(png, am, cid)
        if pdf is not None:
            try:
                top = am.publish_file(
                    pdf,
                    ReportArtifactKind.WATERFALL_PDF,
                    f"waterfalls/{cid}.pdf",
                    created_by_tool=created_by_tool,
                    candidate_id=cid,
                    description="per-candidate waterfall (PDF)",
                )
                am.publish_file(
                    pdf,
                    ReportArtifactKind.WATERFALL_PDF,
                    f"candidates/{cid}/waterfall.pdf",
                    created_by_tool=created_by_tool,
                    candidate_id=cid,
                    description="per-candidate waterfall (PDF)",
                )
                cand.paths.waterfall_pdf_path = top.path
                out.append(top)
            except Exception as e:  # noqa: BLE001
                am.add_warning(f"candidate {cid}: could not publish waterfall PDF: {e}")
            finally:
                pdf.unlink(missing_ok=True)
    return out


def _png_to_pdf(png: Path, am: ArtifactManager, cid: str) -> Path | None:
    """Convert a PNG to a single-page PDF (Pillow). ``None`` on failure."""
    pdf = png.with_name(f"{png.stem}_{cid}.pdf")
    try:
        with Image.open(png) as im:
            im.convert("RGB").save(pdf, "PDF", resolution=150.0)
    except (UnidentifiedImageError, OSError) as e:
        am.add_warning(f"candidate {cid}: PNG->PDF conversion failed: {e}")
        return None
    return pdf


def _select(
    candidates: list[Candidate],
    *,
    selection: CandidateSelection,
    top_n: int,
    candidate_id: str | None,
    min_snr: float | None,
    min_dm: float | None,
    max_dm: float | None,
    am: ArtifactManager,
) -> list[Candidate]:
    """Filter + order candidates for waterfall rendering."""
    pool = [c for c in candidates if c.dm is not None and c.time_sec is not None]

    if min_snr is not None:
        pool = [c for c in pool if c.snr_or_sigma is not None and c.snr_or_sigma >= min_snr]
    if min_dm is not None:
        pool = [c for c in pool if c.dm is not None and c.dm >= min_dm]
    if max_dm is not None:
        pool = [c for c in pool if c.dm is not None and c.dm <= max_dm]

    pool.sort(key=lambda c: (c.rank is None, c.rank or 1_000_000))

    if selection == "one":
        if candidate_id is None:
            am.add_warning("candidate_selection='one' but no candidate_id given")
            return []
        chosen = [c for c in pool if c.candidate_id == candidate_id]
        if not chosen:
            am.add_warning(f"candidate_id {candidate_id!r} not found among waterfall-eligible")
        return chosen
    if selection == "all":
        return pool
    # default: top_n
    return pool[: max(0, top_n)]


__all__ = ["WaterfallFn", "generate_waterfalls"]
