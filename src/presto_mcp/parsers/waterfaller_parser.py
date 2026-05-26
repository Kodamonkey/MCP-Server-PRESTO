"""Parse PRESTO ``waterfaller.py`` output into a typed :class:`WaterfallerResult`.

waterfaller.py renders a dynamic-spectrum waterfall around a given start
time / duration / DM. Upstream PRESTO ``waterfaller.py`` does not accept ``-o``
— it calls ``plt.show()`` directly. The MCP server invokes it via
``bin/waterfaller_headless.py``, which monkeypatches ``plt.show`` to write a
PNG named after the ``WATERFALL_OUTPUT`` env var (default ``waterfall.png``)
into the run's ``artifacts/`` directory. This parser discovers the resulting
file by scanning ``artifacts/`` for ``*.png``/``*.ps``/``*.pdf``.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from ..errors import ParserError
from ..models import WaterfallerCompatNotes, WaterfallerResult

log = logging.getLogger("presto_mcp.parsers.waterfaller")

_BOM = "﻿"


def parse(
    stdout: str,
    run_dir: Path | None = None,
    *,
    input_raw: str = "",
    start_s: float = 0.0,
    duration_s: float = 0.0,
    dm: float = 0.0,
    mask_file: str | None = None,
) -> WaterfallerResult:
    if not isinstance(stdout, str):
        raise ParserError(f"stdout must be str, got {type(stdout).__name__}")
    if stdout.startswith(_BOM):
        stdout = stdout[1:]

    output_file: str | None = None
    compat_notes: WaterfallerCompatNotes | None = None
    if run_dir is not None:
        artifacts_dir = run_dir / "artifacts"
        if artifacts_dir.is_dir():
            for ext in ("*.png", "*.ps", "*.pdf"):
                hits = sorted(artifacts_dir.glob(ext))
                if hits:
                    output_file = hits[0].name
                    break
            notes_path = artifacts_dir / "waterfaller_compat.json"
            if notes_path.is_file():
                try:
                    payload = json.loads(notes_path.read_text(encoding="utf-8"))
                    compat_notes = WaterfallerCompatNotes.model_validate(payload)
                except (OSError, ValueError) as exc:
                    log.warning("failed to load waterfaller compat notes: %s", exc)

    return WaterfallerResult(
        input_raw=input_raw,
        start_s=float(start_s),
        duration_s=float(duration_s),
        dm=float(dm),
        mask_file=mask_file,
        output_file=output_file,
        compat_notes=compat_notes,
    )
