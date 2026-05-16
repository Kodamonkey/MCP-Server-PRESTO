"""FastMCP STDIO server. The only module that imports FastMCP.

Tools registered:

  * ``presto.readfile``        — wraps ``readfile``
  * ``presto.rfifind``         — wraps ``rfifind -time <t> -o <prefix>``
  * ``presto.prepfold``        — wraps ``prepfold -noxwin -p <p> -dm <dm> ...``
  * ``presto.list_runs``       — reflection
  * ``presto.get_run_manifest``— reflection

Resources registered (URI templates):

  * ``presto://runs/{run_id}/manifest``
  * ``presto://runs/{run_id}/stdout``
  * ``presto://runs/{run_id}/stderr``
  * ``presto://runs/{run_id}/artifacts/{filename}``

This file translates between the MCP edge and the typed core. Validation,
sandboxing, and orchestration live in the modules under ``presto_mcp/``.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from . import resources as resource_handlers
from . import tools as _tools_pkg  # noqa: F401 — keep the package side-effect free
from .config import Settings, ensure_runtime_dirs, get_settings, run_health_check
from .docker_backend import BackendProtocol, DockerBackend
from .errors import (
    DockerInvocationError,
    ManifestError,
    ParserError,
    PathSecurityError,
    PolicyViolationError,
)
from .models import (
    PrepfoldResult,
    ReadfileMetadata,
    RfifindSummary,
    RunManifest,
    RunSummary,
    ToolRunResult,
)
from .tools import list_runs as list_runs_tool
from .tools.prepfold import run_prepfold
from .tools.readfile import run_readfile
from .tools.rfifind import run_rfifind

log = logging.getLogger("presto_mcp.server")

# --- App + backend (singletons) ------------------------------------------------

mcp = FastMCP("presto-mcp")


def _build_backend() -> BackendProtocol:
    return DockerBackend()


# Allow tests to install a fake backend before the server boots.
_backend: BackendProtocol | None = None
_settings: Settings | None = None


def _backend_for_tools() -> BackendProtocol:
    global _backend
    if _backend is None:
        _backend = _build_backend()
    return _backend


def _settings_for_tools() -> Settings:
    global _settings
    if _settings is None:
        _settings = get_settings()
    return _settings


def set_backend(b: BackendProtocol) -> None:
    """Tests use this to inject a FakeDockerBackend before the server runs."""
    global _backend
    _backend = b


def set_settings(s: Settings) -> None:
    """Tests use this to inject a Settings before the server runs."""
    global _settings
    _settings = s


# --- Tools ---------------------------------------------------------------------


@mcp.tool(
    name="presto.readfile",
    description=(
        "Run PRESTO 'readfile' inside Docker on a file under data/. Returns "
        "structured metadata (telescope, source name, central freq, channels, "
        "sample time, etc.) plus URIs for manifest/stdout/stderr/artifacts. "
        "Path must be relative to the configured DATA_DIR; absolute paths and "
        "'..' segments are rejected."
    ),
)
async def presto_readfile(
    input_file: Annotated[
        str,
        Field(description="Path to a PRESTO-readable file relative to DATA_DIR."),
    ],
) -> ToolRunResult[ReadfileMetadata]:
    return await asyncio.to_thread(
        run_readfile, input_file, backend=_backend_for_tools(), settings=_settings_for_tools()
    )


@mcp.tool(
    name="presto.rfifind",
    description=(
        "Run PRESTO 'rfifind' inside Docker. Generates .mask/.rfi/.stats "
        "artifacts and a summary (intervals, RFI instances, % masked). "
        "Time is the integration length in seconds (0.1–3600)."
    ),
)
async def presto_rfifind(
    input_file: Annotated[
        str,
        Field(description="Path to a PRESTO-readable file relative to DATA_DIR."),
    ],
    time: Annotated[
        float,
        Field(default=2.0, ge=0.1, le=3600.0, description="Integration length, seconds."),
    ] = 2.0,
    output_prefix: Annotated[
        str | None,
        Field(
            default=None,
            description=(
                "Filename prefix for outputs (alnum, '_', '-', '+', '.'; max 128). "
                "Defaults to 'rfi'."
            ),
        ),
    ] = None,
) -> ToolRunResult[RfifindSummary]:
    return await asyncio.to_thread(
        run_rfifind,
        input_file,
        backend=_backend_for_tools(),
        time=time,
        output_prefix=output_prefix,
        settings=_settings_for_tools(),
    )


@mcp.tool(
    name="presto.prepfold",
    description=(
        "Run PRESTO 'prepfold' inside Docker in Mode A (period + DM). Generates "
        "a .pfd plus .pfd.ps/.pfd.bestprof artifacts. Use this only when you "
        "already have a candidate period and DM; broader 'fold by accel cand' "
        "is a future tool."
    ),
)
async def presto_prepfold(
    input_file: Annotated[
        str,
        Field(description="Path to a PRESTO-readable file relative to DATA_DIR."),
    ],
    period_seconds: Annotated[
        float,
        Field(gt=0.0, le=60.0, description="Candidate spin period in seconds."),
    ],
    dm: Annotated[
        float,
        Field(ge=0.0, le=10_000.0, description="Dispersion measure (pc cm^-3)."),
    ],
    output_prefix: Annotated[
        str | None,
        Field(
            default=None,
            description="Filename prefix for outputs. Defaults to 'fold'.",
        ),
    ] = None,
) -> ToolRunResult[PrepfoldResult]:
    return await asyncio.to_thread(
        run_prepfold,
        input_file,
        period_seconds,
        dm,
        backend=_backend_for_tools(),
        output_prefix=output_prefix,
        settings=_settings_for_tools(),
    )


@mcp.tool(
    name="presto.list_runs",
    description=(
        "List recent PRESTO runs from this server's runs/ directory (newest first). "
        "Returns one row per run with run_id, tool, status, started_at, duration, "
        "exit code and a manifest URI."
    ),
)
async def presto_list_runs(
    limit: Annotated[
        int,
        Field(default=50, ge=1, le=1000, description="Max rows to return."),
    ] = 50,
) -> list[RunSummary]:
    return await asyncio.to_thread(
        list_runs_tool.list_runs, limit=limit, settings=_settings_for_tools()
    )


@mcp.tool(
    name="presto.get_run_manifest",
    description="Return the full manifest JSON for a given run_id.",
)
async def presto_get_run_manifest(
    run_id: Annotated[str, Field(description="A run_id from presto.list_runs.")],
) -> RunManifest:
    return await asyncio.to_thread(
        list_runs_tool.get_run_manifest, run_id, settings=_settings_for_tools()
    )


# --- Resources -----------------------------------------------------------------


@mcp.resource(
    "presto://runs/{run_id}/manifest",
    description="JSON manifest for one PRESTO run.",
    mime_type="application/json",
)
def _resource_manifest(run_id: str) -> str:
    return resource_handlers.read_manifest_resource(_settings_for_tools(), run_id)


@mcp.resource(
    "presto://runs/{run_id}/stdout",
    description="stdout captured for one PRESTO run.",
    mime_type="text/plain",
)
def _resource_stdout(run_id: str) -> str:
    return resource_handlers.read_log_resource(_settings_for_tools(), run_id, "stdout")


@mcp.resource(
    "presto://runs/{run_id}/stderr",
    description="stderr captured for one PRESTO run.",
    mime_type="text/plain",
)
def _resource_stderr(run_id: str) -> str:
    return resource_handlers.read_log_resource(_settings_for_tools(), run_id, "stderr")


@mcp.resource(
    "presto://runs/{run_id}/artifacts/{filename}",
    description=(
        "An artifact produced by a PRESTO run. Small text files are returned "
        "inline; large or binary files return a JSON descriptor pointing at the "
        "host-side path."
    ),
)
def _resource_artifact(run_id: str, filename: str) -> str:
    content, _mime = resource_handlers.read_artifact_resource(
        _settings_for_tools(), run_id, filename
    )
    return content


# --- Entrypoint ----------------------------------------------------------------


def _configure_logging() -> None:
    level = os.environ.get("PRESTO_LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def main() -> None:
    _configure_logging()
    s = get_settings()
    ensure_runtime_dirs(s)
    try:
        run_health_check(s)
    except Exception as e:  # noqa: BLE001
        log.error("startup health check failed: %s", e)
        raise SystemExit(2) from e

    set_settings(s)
    log.info("presto-mcp starting (image=%s, data=%s)", s.image, s.data_dir)
    mcp.run()


# Errors we expect FastMCP to surface as ordinary tool errors. Keeping them
# here as a manifest for readers — FastMCP serializes exception types via repr.
_EXPORTED_ERRORS = (
    PathSecurityError,
    PolicyViolationError,
    DockerInvocationError,
    ParserError,
    ManifestError,
)


if __name__ == "__main__":
    main()
