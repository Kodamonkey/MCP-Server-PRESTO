# PRESTO MCP — Claude Code pointer

**Canonical agent instructions:** [AGENTS.md](./AGENTS.md)

That file is the single source of truth for rules, layout, Docker baseline, definition of done, and validation. Do not duplicate content here.

Quick identity: **PRESTO** radio-astronomy MCP server (not PrestoDB / Apache Pulsar). Host stdio via `uv run python -m presto_mcp.server`; PRESTO runs only inside Docker `alex88ridolfi/presto5:png`.
