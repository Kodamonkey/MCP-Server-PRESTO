"""``presto.compile_candidate_report_pdf`` — bundle run plots into one PDF.

Utility tool (no Docker, no PRESTO execution): it gathers PNG/JPG artifacts
from one or more runs and assembles a single, human-reviewable PDF into a fresh
``runs/<run_id>/artifacts/`` directory.

Security: it reads **only** artifacts under ``runs/`` (via path-security
resolution), never ``data/`` and never absolute paths. Corrupt images are
skipped (not fatal) as long as at least one valid image remains; if no valid
image is found it raises a controlled error. Output order is deterministic and
duplicate images (same content hash) are collapsed.
"""

from __future__ import annotations

import fnmatch
import hashlib
import logging
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from ..config import Settings, get_settings
from ..errors import PathSecurityError, PolicyViolationError
from ..manifest import write_manifest
from ..models import CandidateReportPdfResult, RunManifest, RunStatus, ToolRunResult
from ..path_security import (
    create_run_dir,
    ensure_inside_root,
    is_run_id,
    resolve_run_artifact,
)
from ..policies import check_output_prefix

log = logging.getLogger("presto_mcp.tools.compile_candidate_report_pdf")

_DEFAULT_PATTERNS = ("*.png", "*.jpg", "*.jpeg")
_MAX_IMAGES = 500
_PAGE_W, _PAGE_H = 1240, 1754  # A4 @ ~150 dpi


def _matches(name: str, patterns: tuple[str, ...]) -> bool:
    low = name.lower()
    return any(fnmatch.fnmatch(low, pat.lower()) for pat in patterns)


def _gather(
    run_ids: list[str] | None,
    artifact_paths: list[str] | None,
    patterns: tuple[str, ...],
    s: Settings,
) -> tuple[list[tuple[str, Path]], list[str]]:
    """Return ([(label, host_path)], notes). Labels are '<run_id>/<filename>'."""
    found: list[tuple[str, Path]] = []
    notes: list[str] = []

    for run_id in run_ids or []:
        if not is_run_id(run_id):
            raise PathSecurityError(f"invalid run_id: {run_id!r}")
        artifacts_dir = (s.runs_dir / run_id / "artifacts").resolve()
        ensure_inside_root(artifacts_dir, s.runs_dir)
        if not artifacts_dir.is_dir():
            notes.append(f"{run_id}: no artifacts directory")
            continue
        hits = sorted(
            p for p in artifacts_dir.iterdir()
            if p.is_file() and _matches(p.name, patterns)
        )
        if not hits:
            notes.append(f"{run_id}: no images matching include_patterns")
        for p in hits:
            found.append((f"{run_id}/{p.name}", p))

    for rel in artifact_paths or []:
        host = resolve_run_artifact(rel, s.runs_dir)
        if not _matches(host.name, patterns):
            notes.append(f"{rel}: does not match include_patterns; skipped")
            continue
        rel_norm = rel.replace("\\", "/")
        run_id = rel_norm.split("/", 1)[0]
        found.append((f"{run_id}/{host.name}", host))

    return found, notes


def _dedupe(items: list[tuple[str, Path]]) -> tuple[list[tuple[str, Path]], list[str]]:
    seen_hash: dict[str, str] = {}
    seen_path: set[Path] = set()
    unique: list[tuple[str, Path]] = []
    notes: list[str] = []
    for label, path in items:
        if path in seen_path:
            continue
        seen_path.add(path)
        try:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError as e:
            notes.append(f"{label}: unreadable ({e})")
            continue
        if digest in seen_hash:
            notes.append(f"{label}: duplicate of {seen_hash[digest]}; skipped")
            continue
        seen_hash[digest] = label
        unique.append((label, path))
    return unique, notes


def _sort(
    items: list[tuple[str, Path]], sort_by: str
) -> list[tuple[str, Path]]:
    if sort_by == "mtime":
        return sorted(items, key=lambda lp: lp[1].stat().st_mtime)
    if sort_by == "name":
        return sorted(items, key=lambda lp: lp[1].name.lower())
    # "run_id_name": stable order by the '<run_id>/<filename>' label
    return sorted(items, key=lambda lp: lp[0].lower())


def _title_page(title: str) -> Image.Image:
    page = Image.new("RGB", (_PAGE_W, _PAGE_H), "white")
    draw = ImageDraw.Draw(page)
    try:
        font = ImageFont.load_default(size=48)
    except TypeError:  # Pillow < 10.1: size kwarg unsupported
        font = ImageFont.load_default()
    draw.text((80, _PAGE_H // 2 - 40), title, fill="black", font=font)
    stamp = f"Generated {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}"
    draw.text((80, _PAGE_H // 2 + 40), stamp, fill="black")
    return page


def _fit(img: Image.Image) -> Image.Image:
    """Letterbox one image onto an A4 page so every PDF page is uniform."""
    rgb = img.convert("RGB")
    rgb.thumbnail((_PAGE_W - 80, _PAGE_H - 80))
    page = Image.new("RGB", (_PAGE_W, _PAGE_H), "white")
    page.paste(rgb, ((_PAGE_W - rgb.width) // 2, (_PAGE_H - rgb.height) // 2))
    return page


def run_compile_candidate_report_pdf(
    *,
    run_ids: list[str] | None = None,
    artifact_paths: list[str] | None = None,
    include_patterns: list[str] | None = None,
    title: str | None = None,
    output_prefix: str | None = None,
    sort_by: str = "run_id_name",
    settings: Settings | None = None,
) -> ToolRunResult[CandidateReportPdfResult]:
    """Assemble run image artifacts into one PDF under a fresh run's artifacts/."""
    s = settings or get_settings()
    if not run_ids and not artifact_paths:
        raise PolicyViolationError(
            "compile_candidate_report_pdf requires run_ids and/or artifact_paths"
        )
    if sort_by not in {"run_id_name", "mtime", "name"}:
        raise PolicyViolationError(f"invalid sort_by: {sort_by!r}")
    patterns = tuple(include_patterns) if include_patterns else _DEFAULT_PATTERNS
    prefix = check_output_prefix(output_prefix) if output_prefix else "candidate_report"

    gathered, notes = _gather(run_ids, artifact_paths, patterns, s)
    if not gathered:
        raise PolicyViolationError(
            "no images matched the requested runs / artifact_paths"
        )
    if len(gathered) > _MAX_IMAGES:
        raise PolicyViolationError(
            f"too many images ({len(gathered)}); cap is {_MAX_IMAGES}"
        )

    unique, dedupe_notes = _dedupe(gathered)
    notes.extend(dedupe_notes)
    ordered = _sort(unique, sort_by)

    included: list[str] = []
    skipped: list[str] = []
    pages: list[Image.Image] = []
    if title:
        pages.append(_title_page(title))
    for label, path in ordered:
        try:
            with Image.open(path) as img:
                pages.append(_fit(img))
            included.append(label)
        except Exception as e:  # noqa: BLE001 - corrupt image is non-fatal
            skipped.append(f"{label}: unreadable image ({type(e).__name__})")

    if not included:
        raise PolicyViolationError(
            "no valid images could be read (all candidates were corrupt)"
        )

    started = datetime.now(UTC)
    run_id, run_dir = create_run_dir("compile_candidate_report_pdf", s.runs_dir)
    pdf_name = f"{prefix}.pdf"
    pdf_path = run_dir / "artifacts" / pdf_name
    pages[0].save(
        pdf_path, "PDF", save_all=True, append_images=pages[1:], resolution=150.0
    )
    finished = datetime.now(UTC)

    resource_uri = f"presto://runs/{run_id}/artifacts/{pdf_name}"
    result = CandidateReportPdfResult(
        pdf_file=pdf_name,
        page_count=len(pages),
        title=title,
        included_artifacts=included,
        skipped_artifacts=skipped,
        notes=notes,
        resource_uri=resource_uri,
    )

    manifest = RunManifest(
        run_id=run_id,
        tool="compile_candidate_report_pdf",
        status=RunStatus.SUCCESS,
        exit_code=0,
        started_at=started,
        finished_at=finished,
        duration_s=(finished - started).total_seconds(),
        timeout_s=0,
        image=s.image,
        image_digest=None,
        docker_argv=[],  # local utility tool — no container is launched
        presto_argv=[],
        inputs={
            "run_ids": ",".join(run_ids or []),
            "artifact_paths": ",".join(artifact_paths or []),
            "include_patterns": ",".join(patterns),
            "sort_by": sort_by,
        },
        container_inputs={},
        cpus=0.0,
        memory_mb=0,
        artifacts=[pdf_name],
        error=None,
    )
    write_manifest(run_dir, manifest)

    base = f"presto://runs/{run_id}"
    return ToolRunResult[CandidateReportPdfResult](
        run_id=run_id,
        status=RunStatus.SUCCESS,
        result=result,
        manifest_uri=f"{base}/manifest",
        stdout_uri=f"{base}/stdout",
        stderr_uri=f"{base}/stderr",
        artifact_uris=[resource_uri],
        error=None,
    )


__all__ = ["run_compile_candidate_report_pdf"]
