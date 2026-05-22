"""ArtifactManager — owns the public ``outputs/<run_id>/`` tree.

Responsibilities:

  * create ``outputs/<run_id>/`` and its expected subdirectories,
  * copy / write only **allowed** public artifacts (extension allowlist),
  * keep raw PRESTO intermediates out of the public tree by default,
  * prevent path traversal and accidental overwrites,
  * track warnings / errors,
  * register every artifact and persist ``manifest.json``.

Public artifact extensions: ``.json .csv .html .md .png .pdf``.
Forbidden by default (raw PRESTO): ``.dat .fft .inf .mask .sub* .pfd
.singlepulse[.gz] .ps .eps .log .tmp`` — only ever published, explicitly,
under ``presto_raw_exports/`` via :meth:`ArtifactManager.publish_raw`.
"""

from __future__ import annotations

import logging
import os
import shutil
import time
from pathlib import Path, PurePosixPath

from ..errors import PathSecurityError, ReportingError
from ..path_security import ensure_inside_root
from .schemas import Artifact, ReportArtifactKind, ReportManifest

log = logging.getLogger("presto_mcp.reporting.artifact_manager")

ALLOWED_PUBLIC_EXT: frozenset[str] = frozenset(
    {".json", ".csv", ".html", ".md", ".png", ".pdf"}
)

# Raw PRESTO families never published to the public tree by default.
FORBIDDEN_PUBLIC_EXT: frozenset[str] = frozenset(
    {
        ".dat",
        ".fft",
        ".inf",
        ".mask",
        ".bytemask",
        ".pfd",
        ".bestprof",
        ".singlepulse",
        ".gz",
        ".ps",
        ".eps",
        ".log",
        ".tmp",
        ".rfi",
        ".stats",
    }
)

SUBDIRS: tuple[str, ...] = ("visuals", "thumbnails", "waterfalls", "candidates", "assets")
RAW_EXPORT_DIRNAME = "presto_raw_exports"

_MIME_BY_EXT: dict[str, str] = {
    ".json": "application/json",
    ".csv": "text/csv",
    ".html": "text/html",
    ".md": "text/markdown",
    ".png": "image/png",
    ".pdf": "application/pdf",
}


def is_public_ext(name: str) -> bool:
    """True if ``name``'s final extension is in the public allowlist."""
    return Path(name).suffix.lower() in ALLOWED_PUBLIC_EXT


def is_forbidden_public(name: str) -> bool:
    """True if ``name`` looks like a raw PRESTO intermediate.

    Recognizes the ``.sub####`` subband family and ``.singlepulse.gz``.
    """
    low = name.lower()
    suffix = Path(low).suffix
    if suffix in FORBIDDEN_PUBLIC_EXT:
        return True
    # .sub0001, .sub0002 ... (prepsubband subbands)
    if suffix.startswith(".sub") and suffix[4:].isdigit():
        return True
    return low.endswith(".singlepulse.gz")


def mime_for(name: str) -> str | None:
    return _MIME_BY_EXT.get(Path(name).suffix.lower())


class ArtifactManager:
    """Manage one public report bundle at ``outputs/<run_id>/``."""

    def __init__(self, outputs_root: Path, run_id: str) -> None:
        self.outputs_root = outputs_root.resolve()
        self.run_id = run_id
        self.run_dir = (self.outputs_root / run_id).resolve()
        # run_dir must be a direct child of outputs_root.
        ensure_inside_root(self.run_dir, self.outputs_root)
        if self.run_dir.parent != self.outputs_root:
            raise PathSecurityError(f"run_id must be a single path component: {run_id!r}")

        self.warnings: list[str] = []
        self.errors: list[str] = []
        self.artifacts: list[Artifact] = []
        self._counter = 0

    # -- lifecycle -------------------------------------------------------------

    def create_run(self) -> Path:
        """Create ``outputs/<run_id>/`` and the expected subdirectories."""
        self.run_dir.mkdir(parents=True, exist_ok=True)
        for d in SUBDIRS:
            (self.run_dir / d).mkdir(parents=True, exist_ok=True)
        log.debug("created report run dir %s", self.run_dir)
        return self.run_dir

    @property
    def candidates_dir(self) -> Path:
        return self.run_dir / "candidates"

    def candidate_dir(self, candidate_id: str) -> Path:
        """Return (creating) ``candidates/<candidate_id>/``; id is sanitized."""
        safe = _safe_component(candidate_id)
        d = (self.candidates_dir / safe).resolve()
        ensure_inside_root(d, self.candidates_dir)
        d.mkdir(parents=True, exist_ok=True)
        return d

    # -- diagnostics -----------------------------------------------------------

    def add_warning(self, message: str) -> None:
        self.warnings.append(message)
        log.warning("[%s] %s", self.run_id, message)

    def add_error(self, message: str) -> None:
        self.errors.append(message)
        log.error("[%s] %s", self.run_id, message)

    # -- path helpers ----------------------------------------------------------

    def _safe_target(self, rel_dest: str) -> Path:
        """Resolve ``rel_dest`` to an absolute path strictly inside ``run_dir``."""
        if not isinstance(rel_dest, str) or not rel_dest.strip():
            raise PathSecurityError("artifact destination is empty")
        s = rel_dest.strip().replace("\\", "/")
        if s.startswith("/") or (len(s) >= 2 and s[1] == ":"):
            raise PathSecurityError(f"artifact destination must be relative: {rel_dest!r}")
        parts = [p for p in s.split("/") if p]
        if not parts or any(p in {".", ".."} for p in parts):
            raise PathSecurityError(f"artifact destination has a forbidden segment: {rel_dest!r}")
        target = (self.run_dir / PurePosixPath(s)).resolve(strict=False)
        ensure_inside_root(target, self.run_dir)
        return target

    def relative_path(self, abs_path: Path) -> str:
        """Return ``abs_path`` as a POSIX path relative to ``run_dir``."""
        return abs_path.resolve().relative_to(self.run_dir).as_posix()

    # -- publishing ------------------------------------------------------------

    def _next_artifact_id(self, kind: ReportArtifactKind) -> str:
        self._counter += 1
        return f"{kind.value}-{self._counter:03d}"

    def _register(
        self,
        target: Path,
        kind: ReportArtifactKind,
        *,
        source_file: str | None,
        created_by_tool: str | None,
        candidate_id: str | None,
        description: str | None,
    ) -> Artifact:
        try:
            size = target.stat().st_size
        except OSError:
            size = None
        art = Artifact(
            artifact_id=self._next_artifact_id(kind),
            artifact_kind=kind,
            path=self.relative_path(target),
            source_file=source_file,
            created_by_tool=created_by_tool,
            candidate_id=candidate_id,
            mime_type=mime_for(target.name),
            description=description,
            size_bytes=size,
        )
        self.artifacts.append(art)
        return art

    def publish_file(
        self,
        src: Path,
        kind: ReportArtifactKind,
        rel_dest: str,
        *,
        source_file: str | None = None,
        created_by_tool: str | None = None,
        candidate_id: str | None = None,
        description: str | None = None,
        overwrite: bool = False,
    ) -> Artifact:
        """Copy ``src`` to ``outputs/<run_id>/<rel_dest>`` and register it.

        Rejects non-public extensions and accidental overwrites.
        """
        src = Path(src)
        if not src.is_file():
            raise ReportingError(f"source artifact not found: {src}")
        if not is_public_ext(rel_dest):
            raise ReportingError(
                f"refusing to publish non-public artifact: {rel_dest!r} "
                f"(allowed: {sorted(ALLOWED_PUBLIC_EXT)})"
            )
        target = self._safe_target(rel_dest)
        if target.exists() and not overwrite:
            raise ReportingError(f"artifact already exists, refusing to overwrite: {rel_dest!r}")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target)
        log.debug("published %s -> %s", src, target)
        return self._register(
            target,
            kind,
            source_file=source_file or str(src),
            created_by_tool=created_by_tool,
            candidate_id=candidate_id,
            description=description,
        )

    def write_text(
        self,
        rel_dest: str,
        text: str,
        kind: ReportArtifactKind,
        *,
        created_by_tool: str | None = None,
        candidate_id: str | None = None,
        description: str | None = None,
        overwrite: bool = True,
    ) -> Artifact:
        """Write ``text`` to ``outputs/<run_id>/<rel_dest>`` and register it.

        Used for in-memory artifacts (summary.json, candidates.csv, report.html,
        report.md, per-candidate JSON).
        """
        if not is_public_ext(rel_dest):
            raise ReportingError(f"refusing to write non-public artifact: {rel_dest!r}")
        target = self._safe_target(rel_dest)
        if target.exists() and not overwrite:
            raise ReportingError(f"artifact already exists, refusing to overwrite: {rel_dest!r}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        return self._register(
            target,
            kind,
            source_file=None,
            created_by_tool=created_by_tool,
            candidate_id=candidate_id,
            description=description,
        )

    def publish_raw(
        self,
        src: Path,
        *,
        created_by_tool: str | None = None,
        description: str | None = None,
        overwrite: bool = False,
    ) -> Artifact:
        """Publish a raw PRESTO file under ``presto_raw_exports/``.

        Bypasses the public extension allowlist — caller must have an explicit
        user request for original PRESTO outputs. Still traversal-guarded.
        """
        src = Path(src)
        if not src.is_file():
            raise ReportingError(f"raw source not found: {src}")
        raw_dir = self.run_dir / RAW_EXPORT_DIRNAME
        raw_dir.mkdir(parents=True, exist_ok=True)
        target = (raw_dir / _safe_component(src.name)).resolve()
        ensure_inside_root(target, raw_dir)
        if target.exists() and not overwrite:
            raise ReportingError(f"raw artifact already exists: {src.name}")
        shutil.copy2(src, target)
        return self._register(
            target,
            ReportArtifactKind.RAW_EXPORT,
            source_file=str(src),
            created_by_tool=created_by_tool,
            candidate_id=None,
            description=description or "raw PRESTO output (not a modern MCP artifact)",
        )

    # -- manifest --------------------------------------------------------------

    def artifacts_of(self, kind: ReportArtifactKind) -> list[Artifact]:
        return [a for a in self.artifacts if a.artifact_kind == kind]

    def write_manifest(self, manifest: ReportManifest) -> Path:
        """Persist ``manifest.json`` atomically into ``run_dir``."""
        target = self.run_dir / "manifest.json"
        tmp = target.with_name(f"manifest.json.{os.getpid()}.{time.monotonic_ns()}.tmp")
        tmp.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
        tmp.replace(target)
        log.debug("wrote report manifest %s", target)
        return target


def _safe_component(name: str) -> str:
    """Sanitize one path component (candidate id, filename) — no separators."""
    cleaned = "".join(
        ch if ch.isalnum() or ch in {"_", "-", "."} else "_" for ch in name
    ).strip("._") or "unnamed"
    if cleaned in {".", ".."}:
        return "unnamed"
    return cleaned


__all__ = [
    "ALLOWED_PUBLIC_EXT",
    "FORBIDDEN_PUBLIC_EXT",
    "ArtifactManager",
    "is_forbidden_public",
    "is_public_ext",
    "mime_for",
]
