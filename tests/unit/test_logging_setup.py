from __future__ import annotations

import logging

from presto_mcp.logging_setup import (
    _PhaseFormatter,
    bind_session_log,
    configure_logging,
    phase_logger,
    unbind_session_log,
)


def test_phase_formatter_uses_adapter_phase() -> None:
    adapter = phase_logger("startup", "presto_mcp.test")
    record = adapter.logger.makeRecord(
        "presto_mcp.test",
        logging.INFO,
        __file__,
        1,
        "health check passed",
        (),
        None,
    )
    record.phase = adapter.extra["phase"]
    formatted = _PhaseFormatter("%(asctime)s [%(phase)s] %(message)s").format(record)
    assert "[startup]" in formatted
    assert "health check passed" in formatted


def test_bind_session_log_writes_file(tmp_path) -> None:
    configure_logging(log_to_file=True)
    unbind_session_log()
    session_id = "20260101T120000Z-0001"
    path = bind_session_log(tmp_path, session_id)
    assert path is not None

    log = phase_logger("server", "presto_mcp.server")
    log.info("ready | image=test:tag")

    unbind_session_log()
    text = path.read_text(encoding="utf-8")
    assert "[server]" in text
    assert "ready | image=test:tag" in text
