"""FastMCP STDIO server. The only module that imports FastMCP.

Tool registration lives in ``server_tools.py`` (38 ``presto.*`` tools, profile-gated
via ``PRESTO_TOOL_PROFILE``). Resources and prompts are registered in
``server_resources.py`` and ``server_prompts.py``.

Resources registered (URI templates):

  * ``presto://runs/{run_id}/manifest``
  * ``presto://runs/{run_id}/stdout``
  * ``presto://runs/{run_id}/stderr``
  * ``presto://runs/{run_id}/artifacts/{filename}``

This file translates between the MCP edge and the typed core. Validation,
sandboxing, and orchestration live in the modules under ``presto_mcp/``.
"""

from __future__ import annotations

import logging
import os
import sys

from mcp.server.fastmcp import FastMCP

from .config import (
    HealthCheckError,
    Settings,
    ensure_runtime_dirs,
    format_health_check_failure,
    get_settings,
    run_health_check,
)
from .docker_backend import BackendProtocol, DockerBackend
from .server_prompts import register_prompts
from .server_resources import (
    _resource_artifact,
    _resource_data_index,
    _resource_manifest,
    _resource_run_artifacts,
    _resource_run_summary,
    _resource_runs_index,
    _resource_stderr,
    _resource_stdout,
    register_resources,
)
from .server_tools import register_tools

__all__ = [
    "_resource_artifact",
    "_resource_data_index",
    "_resource_manifest",
    "_resource_run_artifacts",
    "_resource_run_summary",
    "_resource_runs_index",
    "_resource_stderr",
    "_resource_stdout",
]

log = logging.getLogger("presto_mcp.server")

# --- App + backend------------------------------------------------

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


register_tools(mcp, _backend_for_tools, _settings_for_tools)

register_resources(mcp, _settings_for_tools)
register_prompts(mcp)

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
        if isinstance(e, HealthCheckError):
            banner = format_health_check_failure(e)
            print(banner, file=sys.stderr, flush=True)
            log.error("startup health check failed [%s]: %s", e.code, e.summary)
        else:
            log.error("startup health check failed: %s", e)
        raise SystemExit(2) from e

    set_settings(s)
    log.info("presto-mcp starting (image=%s, data=%s)", s.image, s.data_dir)
    mcp.run()


if __name__ == "__main__":
    main()
