from __future__ import annotations

import json

import presto_mcp.audit_log as audit_log
from presto_mcp.config import Settings
from presto_mcp.session_log import SESSION_DIRNAME, reset_state_for_tests


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

    reset_state_for_tests()
    session_id = audit_log.initialize_audit_session(settings)
    audit_log.append_audit_entry(
        settings,
        tool_name="presto.readfile",
        phase="request",
        payload={"input_file": "sample.fil"},
    )
    audit_log.close_audit_session(settings)

    session_file = tmp_path / "logs" / SESSION_DIRNAME / f"{session_id}.jsonl"
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
    reset_state_for_tests()
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

    session_file = settings.logs_dir / SESSION_DIRNAME / f"{session_id}.jsonl"
    lines = session_file.read_text(encoding="utf-8").splitlines()
    rows = [json.loads(line) for line in lines]
    assert rows[1]["session_id"] == session_id
    assert rows[2]["session_id"] == session_id


def test_append_after_close_does_not_create_new_session_file(tmp_path) -> None:
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
    reset_state_for_tests()
    session_id = audit_log.initialize_audit_session(settings)
    audit_log.close_audit_session(settings)

    # No active session after close: must not create a second JSONL.
    audit_log.append_audit_entry(
        settings,
        tool_name="presto.readfile",
        phase="request",
        payload={"input_file": "sample.fil"},
    )

    sessions_dir = settings.logs_dir / SESSION_DIRNAME
    files = sorted(p.name for p in sessions_dir.glob("*.jsonl"))
    assert files == [f"{session_id}.jsonl"]

