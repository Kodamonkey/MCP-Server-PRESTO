"""Modern reporting / artifact layer for the PRESTO MCP server.

PRESTO's native outputs (``.dat``, ``.fft``, ``.pfd``, ``.singlepulse``, ``.ps``…)
are treated here as *internal inputs*. This package turns them into clean,
astronomer-facing artifacts published under ``outputs/<run_id>/``:

  * ``summary.json``     — observational + operational summary
  * ``candidates.csv``   — every parseable candidate, normalized
  * ``visuals/*.png``    — diagnostic plots (collected / converted)
  * ``thumbnails/*.png`` — small previews for the HTML report
  * ``waterfalls/*``     — per-candidate waterfall PNG / PDF
  * ``candidates/<id>/`` — per-candidate detail bundle
  * ``report.html``      — offline scientific dashboard
  * ``report.md``        — lightweight text report
  * ``manifest.json``    — what was produced, with warnings/errors

The layer never modifies PRESTO and never publishes raw intermediate files by
default — see :mod:`presto_mcp.reporting.artifact_manager`.
"""

from __future__ import annotations
