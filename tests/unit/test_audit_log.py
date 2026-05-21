from __future__ import annotations

import json

import presto_mcp.audit_log as audit_log
from presto_mcp.config import Settings


def test_append_audit_entry_writes_jsonl(tmp_path) -> None:
    settings = Settings(
        image="alex88ridolfi/presto5:png",
        data_dir=(tmp_path / "data").resolve(),
        runs_dir=(tmp_path / "runs").resolve(),
        outputs_dir=(tmp_path / "outputs").resolve(),
        logs_dir=(tmp_path / "logs").resolve(),
        default_cpus=2.0,
        default_memory_mb=1024,
        default_timeout_s=60,
        network="none",
        skip_healthcheck=True,
    )

    audit_log._SESSION_STATE.clear()
    session_id = audit_log.initialize_audit_session(settings)
    audit_log.append_audit_entry(
        settings,
        tool_name="presto.readfile",
        phase="request",
        payload={"input_file": "sample.fil"},
    )
    audit_log.close_audit_session(settings)

    session_file = tmp_path / "logs" / "mcp_audit_sessions" / f"{session_id}.jsonl"
    lines = session_file.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    row = json.loads(lines[1])
    assert row["tool"] == "presto.readfile"
    assert row["phase"] == "request"
    assert row["payload"]["input_file"] == "sample.fil"
    assert row["session_id"] == session_id
    assert session_file.is_file()


def test_audit_session_fixed_until_server_stop(tmp_path) -> None:
    settings = Settings(
        image="alex88ridolfi/presto5:png",
        data_dir=(tmp_path / "data").resolve(),
        runs_dir=(tmp_path / "runs").resolve(),
        outputs_dir=(tmp_path / "outputs").resolve(),
        logs_dir=(tmp_path / "logs").resolve(),
        default_cpus=2.0,
        default_memory_mb=1024,
        default_timeout_s=60,
        network="none",
        skip_healthcheck=True,
    )
    audit_log._SESSION_STATE.clear()
    session_id = audit_log.initialize_audit_session(settings)

    audit_log.append_audit_entry(
        settings,
        tool_name="presto.readfile",
        phase="request",
        payload={},
    )
    audit_log.append_audit_entry(
        settings,
        tool_name="presto.rfifind",
        phase="request",
        payload={},
    )
    audit_log.close_audit_session(settings)

    session_file = settings.logs_dir / "mcp_audit_sessions" / f"{session_id}.jsonl"
    lines = session_file.read_text(encoding="utf-8").splitlines()
    rows = [json.loads(line) for line in lines]
    assert rows[1]["session_id"] == session_id
    assert rows[2]["session_id"] == session_id

