from __future__ import annotations
import json
from pathlib import Path
from src.agent.audit import AuditLogger, WeilAuditLogger, stable_hash, bounded_preview


def test_audit_logger_emit_increments_step(tmp_path):
    logger = AuditLogger(tmp_path, "sess-001")
    assert logger.step_index == 0
    logger.emit(event_type="INIT", node="control_loop", status="ok")
    assert logger.step_index == 1
    logger.emit(event_type="INGEST_START", node="ingest", status="ok")
    assert logger.step_index == 2


def test_audit_logger_emit_fields(tmp_path):
    logger = AuditLogger(tmp_path, "sess-002")
    event = logger.emit(
        event_type="TOOL_EXECUTE",
        node="extract_clauses",
        status="ok",
        tool_name="clause_extractor",
        input_payload={"contract_text": "hello"},
        output_payload={"clauses": []},
        latency_ms=42,
        metadata={"attempts": 1},
    )
    assert event.event_type == "TOOL_EXECUTE"
    assert event.node == "extract_clauses"
    assert event.status == "ok"
    assert event.tool_name == "clause_extractor"
    assert event.latency_ms == 42
    assert event.metadata["attempts"] == 1
    assert event.input_hash is not None
    assert event.output_hash is not None


def test_audit_logger_writes_jsonl(tmp_path):
    logger = AuditLogger(tmp_path, "sess-003")
    logger.emit(event_type="INIT", node="control_loop", status="ok")
    logger.emit(event_type="TERMINATE", node="terminate", status="ok")
    lines = logger.jsonl_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    for line in lines:
        obj = json.loads(line)
        assert "event_type" in obj
        assert "step_index" in obj


def test_audit_logger_summary(tmp_path):
    logger = AuditLogger(tmp_path, "sess-004")
    logger.emit(event_type="INIT", node="control_loop", status="ok")
    summary_path = tmp_path / "sess-004" / "audit_summary.json"
    result = logger.summary(
        summary_path,
        final_status="ok",
        extra={"terminate_reason": "complete", "decision": "auto-approved"},
    )
    assert result["session_id"] == "sess-004"
    assert result["event_count"] == 1
    assert result["final_status"] == "ok"
    assert summary_path.exists()
    data = json.loads(summary_path.read_text(encoding="utf-8"))
    assert data["session_id"] == "sess-004"


def test_stable_hash_deterministic():
    h1 = stable_hash({"key": "value", "num": 42})
    h2 = stable_hash({"num": 42, "key": "value"})
    assert h1 == h2
    assert len(h1) == 16
    assert all(c in "0123456789abcdef" for c in h1)


def test_stable_hash_different_for_different_inputs():
    assert stable_hash("hello") != stable_hash("world")


def test_bounded_preview_short_string():
    text = "Short text"
    assert bounded_preview(text) == "Short text"


def test_bounded_preview_long_string():
    text = "A" * 200
    result = bounded_preview(text, limit=120)
    assert result.endswith("...")
    assert len(result) == 123  # 120 chars + "..."


def test_weil_audit_logger_disabled_when_no_sdk(tmp_path):
    # With no wallet file, should be disabled
    logger = WeilAuditLogger(str(tmp_path / "nonexistent.wc"))
    assert logger.enabled is False
    assert logger.tx_results == []


def test_weil_audit_logger_auth_headers_empty_when_disabled(tmp_path):
    logger = WeilAuditLogger(str(tmp_path / "nonexistent.wc"))
    headers = logger.get_auth_headers()
    assert headers == {}


def test_weil_audit_logger_emit_noop_when_disabled(tmp_path):
    logger = WeilAuditLogger(str(tmp_path / "nonexistent.wc"))
    # Should not raise
    logger.emit("INIT", {"node": "test", "status": "ok"})
    assert logger.tx_results == []
