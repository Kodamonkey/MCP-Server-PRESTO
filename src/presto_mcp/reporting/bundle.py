"""Orchestrator for the modern report bundle.

:func:`generate_bundle` is the single core entry point behind all seven
reporting MCP tools. It reads raw PRESTO outputs from one or more internal
workdirs and publishes only the modern artifacts requested by an
:class:`ArtifactPolicy` into ``outputs/<run_id>/``.

The dedicated single-purpose tools call this with a narrow policy; the
``generate_modern_report_bundle`` tool routes a full policy from intention
flags.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from ..config import REPO_ROOT, Settings
from ..docker_backend import BackendProtocol
from ..errors import PathSecurityError, ReportingError
from ..models import RunStatus
from ..observability.logging_config import load_logging_settings
from ..observability.run_tracker import RunTracker
from ..observability.structured_logger import get_structured_logger
from ..path_security import ensure_inside_root, is_run_id, new_run_id
from ..run_label import report_bundle_dirname
from .artifact_manager import ArtifactManager
from .candidate_parser import candidates_to_csv, parse_candidates
from .html_report_builder import build_html
from .markdown_report_builder import build_markdown
from .output_index import write_output_index
from .schemas import (
    Artifact,
    ArtifactPolicy,
    Candidate,
    ReportArtifactKind,
    ReportManifest,
    ReportOptions,
    ReportToolResult,
    RunReportSummary,
)
from .summary_builder import build_summary
from .visual_builder import collect_visuals
from .waterfall_builder import WaterfallFn, generate_waterfalls

log = logging.getLogger("presto_mcp.reporting.bundle")

# Forbidden public extensions that may still be exported as *raw* PRESTO output.
_RAW_EXPORT_SUFFIXES = (
    ".dat",
    ".fft",
    ".inf",
    ".mask",
    ".pfd",
    ".bestprof",
    ".singlepulse",
    ".ps",
    ".eps",
)
_CANDIDATE_JSON_LIMIT = 50


def resolve_roots(
    run_ids: list[str] | None,
    workdir: str | None,
    settings: Settings,
) -> list[Path]:
    """Resolve ``run_ids`` / ``workdir`` to validated directories under ``runs/``."""
    roots: list[Path] = []
    runs_root = settings.runs_dir.resolve()

    for rid in run_ids or []:
        if not is_run_id(rid):
            raise PathSecurityError(f"invalid run_id: {rid!r}")
        d = (runs_root / rid).resolve()
        ensure_inside_root(d, runs_root)
        if not d.is_dir():
            raise ReportingError(f"run directory not found: {rid}")
        roots.append(d)

    if workdir:
        w = workdir.strip().replace("\\", "/")
        if w.startswith("/") or (len(w) >= 2 and w[1] == ":"):
            raise PathSecurityError(f"workdir must be relative to runs/: {workdir!r}")
        if ".." in w.split("/"):
            raise PathSecurityError(f"workdir has a forbidden segment: {workdir!r}")
        d = (runs_root / w).resolve()
        ensure_inside_root(d, runs_root)
        if not d.is_dir():
            raise ReportingError(f"workdir not found under runs/: {workdir}")
        roots.append(d)

    if not roots:
        raise ReportingError("no workdir given: provide run_ids and/or workdir")
    return roots


def _find_preferred_waterfall_mask(
    roots: list[Path],
    settings: Settings,
) -> str | None:
    """Return best available mask ref as ``<run_id>/artifacts/<name>.mask``."""
    runs_root = settings.runs_dir.resolve()
    ranked: list[tuple[int, float, str]] = []

    def _as_ref(mask_path: Path) -> str | None:
        try:
            rel = mask_path.resolve().relative_to(runs_root)
        except ValueError:
            return None
        return rel.as_posix()

    for root in roots:
        root = Path(root)
        if not root.is_dir():
            continue

        # Highest-priority source: successful rfifind run's artifacts/*.mask.
        manifest_path = root / "manifest.json"
        if manifest_path.is_file():
            try:
                mdata = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                mdata = {}
            if (
                isinstance(mdata, dict)
                and str(mdata.get("tool", "")) == "rfifind"
                and str(mdata.get("status", "")).upper() == "SUCCESS"
            ):
                for mask in sorted((root / "artifacts").glob("*.mask")):
                    ref = _as_ref(mask)
                    if ref is not None:
                        ranked.append((2, mask.stat().st_mtime, ref))

        # Fallback source: any mask below selected roots.
        for mask in sorted(root.rglob("*.mask")):
            ref = _as_ref(mask)
            if ref is not None:
                ranked.append((1, mask.stat().st_mtime, ref))

    if not ranked:
        return None
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return ranked[0][2]


def make_waterfall_fn(
    backend: BackendProtocol,
    settings: Settings,
    *,
    mask_file: str | None = None,
) -> WaterfallFn:
    """Build a waterfall renderer backed by the containerized PRESTO waterfaller."""
    from ..tools.waterfaller import run_waterfaller

    def _render(
        *,
        input_file: str,
        start_s: float,
        duration_s: float,
        dm: float,
        cmap: str,
        candidate_id: str,
    ) -> Path | None:
        result = run_waterfaller(
            input_file,
            backend=backend,
            start_s=start_s,
            duration_s=duration_s,
            dm=dm,
            mask_file=mask_file,
            colour_map=cmap,
            nsub=None,
            nbins=None,
            downsamp=None,
            settings=settings,
            background=False,
        )
        if result.status != RunStatus.SUCCESS or result.result is None:
            stderr_tail = ""
            stderr_path = settings.runs_dir / result.run_id / "stderr.log"
            try:
                if stderr_path.is_file():
                    tail = stderr_path.read_text(encoding="utf-8", errors="replace").splitlines()
                    stderr_tail = tail[-1] if tail else ""
            except OSError:
                stderr_tail = ""
            detail = result.error or stderr_tail or "unknown error"
            raise RuntimeError(
                f"waterfaller backend failed (run_id={result.run_id}): {detail}"
            )
        output_file = result.result.output_file
        if not output_file:
            raise RuntimeError(
                f"waterfaller backend produced no output image (run_id={result.run_id})"
            )
        png = settings.runs_dir / result.run_id / "artifacts" / output_file
        if not png.is_file():
            raise RuntimeError(
                f"waterfaller output not found in artifacts (run_id={result.run_id}, file={output_file})"
            )
        return png

    return _render


def generate_bundle(
    *,
    tool_name: str,
    run_ids: list[str] | None,
    workdir: str | None,
    input_file: str | None,
    policy: ArtifactPolicy,
    options: ReportOptions,
    settings: Settings,
    backend: BackendProtocol | None = None,
    waterfall_selection: str = "top_n",
    waterfall_top_n: int = 10,
    waterfall_candidate_id: str | None = None,
    waterfall_min_snr: float | None = None,
    waterfall_min_dm: float | None = None,
    waterfall_max_dm: float | None = None,
    waterfall_window_sec: float | None = None,
) -> ReportToolResult:
    """Produce a modern report bundle and return a typed result envelope."""
    generated_at = datetime.now(UTC)
    roots = resolve_roots(run_ids, workdir, settings)

    run_id = new_run_id()
    bundle_dir = report_bundle_dirname(input_file, generated_at.strftime("%Y%m%dT%H%M%SZ"))
    am = ArtifactManager(settings.outputs_dir, bundle_dir)
    am.create_run()

    tracker = _make_tracker(run_id, tool_name)
    if tracker is not None:
        tracker.workflow_started(tool_name)
        _track_presto_runs(tracker, roots)

    candidates, parse_warnings = parse_candidates(roots)
    for w in parse_warnings:
        am.add_warning(w)
    _step(tracker, "parse candidates", notes=f"{len(candidates)} candidates")

    summary_rel: str | None = None
    csv_rel: str | None = None
    html_rel: str | None = None
    md_rel: str | None = None

    # 1. candidates.csv
    if policy.export_candidates_csv:
        csv_text = candidates_to_csv(candidates, run_id=run_id, input_file=input_file)
        art = am.write_text(
            "candidates.csv",
            csv_text,
            ReportArtifactKind.CANDIDATES_CSV,
            created_by_tool=tool_name,
            description="normalized candidate table",
        )
        csv_rel = art.path
        _step(tracker, "export candidates.csv", notes=f"{len(candidates)} rows")

    # 2. visuals + thumbnails
    if policy.export_visual_png:
        collect_visuals(roots, am, make_thumbnails=policy.export_thumbnails)
        _step(tracker, "collect visual artifacts")

    # 3. per-candidate waterfalls
    if policy.export_waterfall_png or policy.export_waterfall_pdf:
        # Prefer canonical PRESTO single-pulse diagnostics (.spd / plot_spd) when
        # they exist in the supplied roots — these are PRESTO's authoritative
        # output and outrank the MCP-side waterfaller quicklook.
        spd_published = _publish_existing_spd_plots(roots, am, tool_name)
        if spd_published > 0:
            am.add_warning(
                f"surfaced {spd_published} canonical plot_spd diagnostic(s); "
                "MCP-side waterfaller quicklook was skipped because .spd output exists"
            )
            _step(
                tracker,
                "surface canonical plot_spd diagnostics",
                tool="presto_plot_spd",
                notes=f"{spd_published} PNG",
            )
        else:
            _run_waterfalls(
                roots,
                candidates,
                am,
                policy=policy,
                options=options,
                settings=settings,
                backend=backend,
                input_file=input_file,
                tool_name=tool_name,
                selection=waterfall_selection,
                top_n=waterfall_top_n,
                candidate_id=waterfall_candidate_id,
                min_snr=waterfall_min_snr,
                min_dm=waterfall_min_dm,
                max_dm=waterfall_max_dm,
                window_sec=waterfall_window_sec,
            )
            _step(
                tracker,
                "generate candidate waterfalls",
                tool="presto_waterfaller",
                notes=f"{len(am.artifacts_of(ReportArtifactKind.WATERFALL_PNG))} PNG",
            )

    # 4. per-candidate JSON (when a report or waterfalls are produced)
    if policy.export_report_html or policy.export_waterfall_png:
        _write_candidate_jsons(candidates, am, tool_name)

    # 5. raw PRESTO exports (explicit opt-in only)
    if policy.export_original_presto_outputs:
        _export_raw(roots, am, tool_name)

    # The summary object is always built (HTML/MD need it); only persisted on policy.
    summary = build_summary(
        run_id=run_id,
        input_file=input_file,
        roots=roots,
        candidates=candidates,
        policy=policy,
        generated_at=generated_at,
        warnings=am.warnings,
        errors=am.errors,
    )

    # Finalize observability and mirror status.md / timeline.json into the bundle.
    obs_log_paths: dict[str, str] = {}
    obs_status_rel: str | None = None
    obs_timeline_rel: str | None = None
    if tracker is not None:
        tracker.workflow_completed(summary.status)
        obs_log_paths, obs_status_rel, obs_timeline_rel = _publish_observability(
            am, tracker, tool_name
        )
        summary.logs_available = True
        summary.status_file = obs_status_rel

    # 6. summary.json
    if policy.export_summary_json:
        art = am.write_text(
            "summary.json",
            summary.model_dump_json(indent=2),
            ReportArtifactKind.SUMMARY_JSON,
            created_by_tool=tool_name,
            description="observation + workflow summary",
        )
        summary_rel = art.path

    # Build the manifest before HTML/MD so they can link to it.
    manifest = _build_manifest(
        run_id=run_id,
        input_file=input_file,
        created_at=generated_at,
        summary=summary,
        policy=policy,
        am=am,
        summary_rel=summary_rel,
        csv_rel=csv_rel,
    )
    manifest.log_paths = obs_log_paths
    manifest.status_md = obs_status_rel
    manifest.timeline_json = obs_timeline_rel

    # 7. report.html
    if policy.export_report_html:
        html_doc = build_html(
            summary=summary,
            candidates=candidates,
            am=am,
            options=options,
            manifest=manifest,
        )
        art = am.write_text(
            "report.html",
            html_doc,
            ReportArtifactKind.REPORT_HTML,
            created_by_tool=tool_name,
            description="offline HTML dashboard",
        )
        html_rel = art.path
        manifest.report_html = html_rel

    # 8. report.md
    if policy.export_report_markdown:
        md_doc = build_markdown(
            summary=summary,
            candidates=candidates,
            options=options,
            manifest=manifest,
        )
        art = am.write_text(
            "report.md",
            md_doc,
            ReportArtifactKind.REPORT_MD,
            created_by_tool=tool_name,
            description="lightweight Markdown report",
        )
        md_rel = art.path
        manifest.report_md = md_rel

    manifest.warnings = list(am.warnings)
    manifest.errors = list(am.errors)
    manifest.status = summary.status
    am.write_manifest(manifest)

    write_output_index(settings.outputs_dir)

    return ReportToolResult(
        run_id=run_id,
        tool=tool_name,
        status=summary.status,  # type: ignore[arg-type]
        output_dir=str(am.run_dir),
        manifest_path="manifest.json",
        summary_json=summary_rel,
        candidates_csv=csv_rel,
        report_html=html_rel,
        report_md=md_rel,
        candidate_count=len(candidates),
        artifact_count=len(am.artifacts),
        artifacts=list(am.artifacts),
        warnings=list(am.warnings),
        errors=list(am.errors),
    )


# -- internal steps ------------------------------------------------------------


def _run_waterfalls(
    roots: list[Path],
    candidates: list[Candidate],
    am: ArtifactManager,
    *,
    policy: ArtifactPolicy,
    options: ReportOptions,
    settings: Settings,
    backend: BackendProtocol | None,
    input_file: str | None,
    tool_name: str,
    selection: str,
    top_n: int,
    candidate_id: str | None,
    min_snr: float | None,
    min_dm: float | None,
    max_dm: float | None,
    window_sec: float | None,
) -> None:
    if input_file is None:
        am.add_warning("waterfalls requested but no input_file given; skipped")
        return
    if backend is None:
        am.add_warning("waterfalls requested but no Docker backend available; skipped")
        return
    mask_ref = _find_preferred_waterfall_mask(roots, settings)
    if mask_ref:
        log.info("waterfaller using rfifind mask: %s", mask_ref)
    waterfall_fn = make_waterfall_fn(backend, settings, mask_file=mask_ref)
    generate_waterfalls(
        candidates,
        am,
        policy=policy,
        options=options,
        waterfall_fn=waterfall_fn,
        input_file=input_file,
        selection=selection,
        top_n=top_n,
        candidate_id=candidate_id,
        min_snr=min_snr,
        min_dm=min_dm,
        max_dm=max_dm,
        time_window_sec=window_sec,
        export_png=policy.export_waterfall_png,
        export_pdf=policy.export_waterfall_pdf,
        created_by_tool=tool_name,
    )


def _publish_existing_spd_plots(
    roots: list[Path],
    am: ArtifactManager,
    tool_name: str,
) -> int:
    """Surface plot_spd PNGs from supplied roots as canonical single-pulse diagnostics.

    Returns the number of canonical diagnostics published. PRESTO's
    authoritative single-pulse diagnostic is ``plot_spd`` output (rendered
    from a ``.spd`` file produced by ``make_spd``). When such PNGs are
    present in any of the supplied ``run_ids`` we publish them with the
    ``WATERFALL_PNG`` kind so they appear in the report bundle in place of
    the MCP-side waterfaller quicklook.

    A root is treated as a plot_spd source if it contains either:
      * an ``artifacts/*.spd`` file (it was a make_spd run, with rendered PNGs
        next to the SPD), or
      * a ``manifest.json`` whose ``tool`` is ``plot_spd``.

    PNGs found alongside are published as
    ``waterfalls/spd-<run_id>-<basename>.png``.
    """
    seen_names: set[str] = set()
    published = 0
    for root in roots:
        if not root.is_dir():
            continue
        artifacts = root / "artifacts"
        if not artifacts.is_dir():
            continue

        manifest_tool = ""
        manifest_path = root / "manifest.json"
        if manifest_path.is_file():
            try:
                mdata = json.loads(manifest_path.read_text(encoding="utf-8"))
                manifest_tool = str(mdata.get("tool", ""))
            except (OSError, json.JSONDecodeError):
                pass

        has_spd = any(artifacts.glob("*.spd"))
        if not (manifest_tool == "plot_spd" or has_spd):
            continue

        for png in sorted(artifacts.glob("*.png")):
            if png.name in seen_names:
                continue
            seen_names.add(png.name)
            rel = f"waterfalls/spd-{root.name}-{png.stem}.png"
            try:
                am.publish_file(
                    png,
                    ReportArtifactKind.WATERFALL_PNG,
                    rel,
                    created_by_tool=tool_name,
                    description="canonical single-pulse diagnostic (plot_spd)",
                )
                published += 1
            except Exception as e:  # noqa: BLE001
                am.add_warning(
                    f"could not publish plot_spd PNG {png.name}: {e}"
                )
    return published


def _write_candidate_jsons(
    candidates: list[Candidate], am: ArtifactManager, tool_name: str
) -> None:
    """Write ``candidates/<id>/candidate.json`` for the most relevant candidates."""
    ordered = sorted(
        candidates,
        key=lambda c: (c.paths.waterfall_png_path is None, c.rank or 1_000_000),
    )
    for cand in ordered[:_CANDIDATE_JSON_LIMIT]:
        rel = f"candidates/{cand.candidate_id}/candidate.json"
        try:
            art = am.write_text(
                rel,
                json.dumps(cand.model_dump(mode="json"), indent=2, ensure_ascii=True),
                ReportArtifactKind.CANDIDATE_JSON,
                created_by_tool=tool_name,
                candidate_id=cand.candidate_id,
                description="per-candidate metadata",
            )
            cand.paths.candidate_json_path = art.path
        except Exception as e:  # noqa: BLE001
            am.add_warning(f"candidate {cand.candidate_id}: could not write candidate.json: {e}")


def _export_raw(roots: list[Path], am: ArtifactManager, tool_name: str) -> None:
    seen: set[str] = set()
    for root in roots:
        for p in sorted(root.rglob("*")):
            if not p.is_file() or p.suffix.lower() not in _RAW_EXPORT_SUFFIXES:
                continue
            if p.name in seen:
                continue
            seen.add(p.name)
            try:
                am.publish_raw(p, created_by_tool=tool_name)
            except Exception as e:  # noqa: BLE001
                am.add_warning(f"could not export raw {p.name}: {e}")


def _make_tracker(run_id: str, workflow_name: str) -> RunTracker | None:
    """Create a best-effort :class:`RunTracker` for this bundle (never fatal)."""
    try:
        log_settings = load_logging_settings(REPO_ROOT)
        if not log_settings.enabled:
            return None
        return RunTracker(
            run_id,
            log_settings,
            structured_logger=get_structured_logger(),
            workflow_name=workflow_name,
        )
    except Exception as e:  # noqa: BLE001 - observability must never break a bundle
        log.warning("could not create run tracker: %s", e)
        return None


def _step(
    tracker: RunTracker | None,
    step: str,
    *,
    tool: str | None = None,
    status: str = "completed",
    notes: str | None = None,
) -> None:
    if tracker is None:
        return
    try:
        tracker.step(step, tool=tool, status=status, notes=notes)
    except Exception as e:  # noqa: BLE001
        log.debug("run tracker step failed: %s", e)


def _track_presto_runs(tracker: RunTracker, roots: list[Path]) -> None:
    """Add one status row per consolidated PRESTO run (from its manifest)."""
    from .summary_builder import _scan_run_manifests

    try:
        for m in _scan_run_manifests(roots):
            tool = str(m.get("tool") or "presto")
            status = str(m.get("status", "")).upper()
            row_status = "completed"
            if status in {"FAILED", "TIMEOUT"}:
                row_status = "failed"
            duration = m.get("duration_s")
            tracker.step(
                f"PRESTO {tool}",
                tool=tool,
                tool_call_id=str(m.get("run_id") or "") or None,
                status=row_status,
                duration_s=float(duration) if isinstance(duration, int | float) else None,
                notes=f"exit={m.get('exit_code')}",
            )
    except Exception as e:  # noqa: BLE001
        log.debug("tracking PRESTO runs failed: %s", e)


def _publish_observability(
    am: ArtifactManager, tracker: RunTracker, tool_name: str
) -> tuple[dict[str, str], str | None, str | None]:
    """Mirror status.md + timeline.json into the bundle; return their rel paths."""
    log_paths: dict[str, str] = {}
    status_rel: str | None = None
    timeline_rel: str | None = None
    try:
        log_paths = tracker.log_paths()
    except Exception as e:  # noqa: BLE001
        log.debug("tracker.log_paths failed: %s", e)
    try:
        if tracker.status_md.is_file():
            art = am.publish_file(
                tracker.status_md,
                ReportArtifactKind.ASSET,
                "status.md",
                created_by_tool=tool_name,
                description="workflow status table",
                overwrite=True,
            )
            status_rel = art.path
    except Exception as e:  # noqa: BLE001
        am.add_warning(f"could not publish status.md: {e}")
    try:
        if tracker.timeline_json.is_file():
            art = am.publish_file(
                tracker.timeline_json,
                ReportArtifactKind.ASSET,
                "timeline.json",
                created_by_tool=tool_name,
                description="workflow timeline",
                overwrite=True,
            )
            timeline_rel = art.path
    except Exception as e:  # noqa: BLE001
        am.add_warning(f"could not publish timeline.json: {e}")
    return log_paths, status_rel, timeline_rel


def _build_manifest(
    *,
    run_id: str,
    input_file: str | None,
    created_at: datetime,
    summary: RunReportSummary,
    policy: ArtifactPolicy,
    am: ArtifactManager,
    summary_rel: str | None,
    csv_rel: str | None,
) -> ReportManifest:
    def of(kind: ReportArtifactKind) -> list[Artifact]:
        return am.artifacts_of(kind)

    return ReportManifest(
        run_id=run_id,
        input_file=input_file,
        created_at=created_at,
        status=summary.status,  # type: ignore[arg-type]
        tools_executed=summary.tools_executed,
        artifact_policy=policy,
        summary_json=summary_rel,
        candidates_csv=csv_rel,
        report_html=None,
        report_md=None,
        visuals=of(ReportArtifactKind.VISUAL_PNG),
        thumbnails=of(ReportArtifactKind.THUMBNAIL),
        waterfall_png=of(ReportArtifactKind.WATERFALL_PNG),
        waterfall_pdf=of(ReportArtifactKind.WATERFALL_PDF),
        candidate_artifacts=of(ReportArtifactKind.CANDIDATE_JSON),
        raw_presto_exports=of(ReportArtifactKind.RAW_EXPORT),
        warnings=list(am.warnings),
        errors=list(am.errors),
    )


__all__ = ["generate_bundle", "make_waterfall_fn", "resolve_roots"]
