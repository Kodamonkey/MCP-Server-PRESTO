"""Probe the configured PRESTO image and emit a runtime compatibility report.

Standalone (no MCP server runtime). Used by the ``runtime-compatibility`` CI
workflow. Writes ``runtime_compatibility.json`` and ``tool_readiness.md`` into
the current working directory.
"""

from __future__ import annotations

from pathlib import Path

from presto_mcp.config import ensure_runtime_dirs, get_settings
from presto_mcp.docker_backend import DockerBackend
from presto_mcp.runtime_checks import collect_runtime_compatibility


def main() -> None:
    settings = get_settings()
    ensure_runtime_dirs(settings)
    backend = DockerBackend()
    compat = collect_runtime_compatibility(backend, settings, force_refresh=True)

    Path("runtime_compatibility.json").write_text(
        compat.model_dump_json(indent=2), encoding="utf-8"
    )

    lines = [
        f"# Tool readiness — {compat.image}",
        "",
        f"Overall status: **{compat.status}**",
        "",
        "| Tool | Status | Blocking | Checks |",
        "|------|--------|----------|--------|",
    ]
    for r in compat.tool_readiness:
        checks = ", ".join(f"{c.name}={c.status}" for c in r.checks) or "—"
        lines.append(f"| {r.tool_name} | {r.status} | {r.blocking} | {checks} |")
    Path("tool_readiness.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"runtime compatibility: {compat.status} for image {compat.image}")


if __name__ == "__main__":
    main()
