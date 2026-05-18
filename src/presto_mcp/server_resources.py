"""MCP resource registration for ``presto_mcp.server``.

No FastMCP import lives here; the entrypoint passes the app object in.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from . import resources as resource_handlers
from .config import Settings
from .tools import list_runs as list_runs_tool
from .tools.list_data_files import run_list_data_files
from .tools.summarize_run import inspect_artifacts as _inspect_artifacts
from .tools.summarize_run import summarize_run as _summarize_run

_settings_for_tools: Callable[[], Settings] | None = None


def _settings() -> Settings:
    if _settings_for_tools is None:
        raise RuntimeError("resource registration has not been initialized")
    return _settings_for_tools()


def _resource_manifest(run_id: str) -> str:
    return resource_handlers.read_manifest_resource(_settings(), run_id)


def _resource_stdout(run_id: str) -> str:
    return resource_handlers.read_log_resource(_settings(), run_id, "stdout")


def _resource_stderr(run_id: str) -> str:
    return resource_handlers.read_log_resource(_settings(), run_id, "stderr")


def _resource_artifact(run_id: str, filename: str) -> str:
    content, _mime = resource_handlers.read_artifact_resource(_settings(), run_id, filename)
    return content


def _resource_data_index() -> str:
    result = run_list_data_files(settings=_settings())
    return result.model_dump_json(indent=2)


def _resource_runs_index() -> str:
    summaries = list_runs_tool.list_runs(settings=_settings())
    payload = [s.model_dump(mode="json") for s in summaries]
    return json.dumps({"count": len(payload), "runs": payload}, indent=2)


def _resource_run_summary(run_id: str) -> str:
    return _summarize_run(run_id, settings=_settings()).model_dump_json(indent=2)


def _resource_run_artifacts(run_id: str) -> str:
    return _inspect_artifacts(run_id, settings=_settings()).model_dump_json(indent=2)


def register_resources(
    mcp: Any,
    settings_for_tools: Callable[[], Settings],
) -> None:
    global _settings_for_tools
    _settings_for_tools = settings_for_tools

    mcp.resource(
        "presto://runs/{run_id}/manifest",
        description="JSON manifest for one PRESTO run.",
        mime_type="application/json",
    )(_resource_manifest)
    mcp.resource(
        "presto://runs/{run_id}/stdout",
        description="stdout captured for one PRESTO run.",
        mime_type="text/plain",
    )(_resource_stdout)
    mcp.resource(
        "presto://runs/{run_id}/stderr",
        description="stderr captured for one PRESTO run.",
        mime_type="text/plain",
    )(_resource_stderr)
    mcp.resource(
        "presto://runs/{run_id}/artifacts/{filename}",
        description=(
            "An artifact produced by a PRESTO run. Small text files are returned "
            "inline; large or binary files return a JSON descriptor pointing at the "
            "host-side path."
        ),
    )(_resource_artifact)
    mcp.resource(
        "presto://data",
        description="JSON index of files under PRESTO_DATA_DIR (relative paths only).",
        mime_type="application/json",
    )(_resource_data_index)
    mcp.resource(
        "presto://runs",
        description="JSON index of recent runs (newest first).",
        mime_type="application/json",
    )(_resource_runs_index)
    mcp.resource(
        "presto://runs/{run_id}/summary",
        description="Structured RunStructuredSummary JSON for one run.",
        mime_type="application/json",
    )(_resource_run_summary)
    mcp.resource(
        "presto://runs/{run_id}/artifacts",
        description="JSON index of artifacts for one run (no inlined contents).",
        mime_type="application/json",
    )(_resource_run_artifacts)
