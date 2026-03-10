from __future__ import annotations

import json
from pathlib import Path

import main
from src.tools.router import ToolRouter, ToolSpec
from tests.conftest import InMemoryMCPClient


def test_cli_json_output(monkeypatch, capsys, tmp_path) -> None:
    contract_path = tmp_path / "contract.txt"
    contract_path.write_text("Basic contract text", encoding="utf-8")

    monkeypatch.setattr(
        main.sys,
        "argv",
        ["main.py", "--input", str(contract_path), "--format", "json", "--no-human-gate"],
    )

    # Patch ToolRouter construction to use in-memory mock instead of real MCP
    original_init = ToolRouter.__init__

    def patched_init(self, settings, mcp_client=None):
        def clause_extractor(payload: dict) -> dict:
            return {"clauses": [{"id": 1, "title": "Clause 1", "text": payload.get("contract_text", "")}]}

        def risk_scorer(payload: dict) -> dict:
            return {"risk": {"risk_level": "LOW", "confidence": "0.8", "reason": "Safe", "flags": []}}

        original_init(
            self,
            settings=settings,
            mcp_client=InMemoryMCPClient({"clause_extractor": clause_extractor, "risk_scorer": risk_scorer}),
        )

    monkeypatch.setattr(ToolRouter, "__init__", patched_init)

    exit_code = main.main()
    output = capsys.readouterr().out

    assert exit_code == 0
    payload = json.loads(output)
    assert payload["session_id"]
    assert "audit_log" in payload


def test_cli_with_sample_high_risk_contract(monkeypatch, capsys, tmp_path) -> None:
    """Run with contracts/sample_high_risk.txt and verify HIGH risk detection."""
    from pathlib import Path
    import uuid

    # Use the actual sample_high_risk.txt from contracts dir
    contract_path = Path(__file__).parent.parent / "contracts" / "sample_high_risk.txt"
    if not contract_path.exists():
        # Fallback: create a high-risk contract for testing
        contract_path = tmp_path / "high_risk.txt"
        contract_path.write_text(
            "NON-COMPETE: Consultant shall not work for any competitor worldwide for 10 years. "
            "PENALTY: Violation results in $1,000,000 penalty with no liability cap.",
            encoding="utf-8",
        )

    monkeypatch.setattr(
        main.sys,
        "argv",
        ["main.py", "--input", str(contract_path), "--format", "json", "--no-human-gate"],
    )

    # Patch ToolRouter to use mocks
    original_init = ToolRouter.__init__

    def patched_init(self, settings, mcp_client=None):
        def clause_extractor(payload: dict) -> dict:
            return {
                "clauses": [
                    {"id": 1, "title": "Non-Compete", "text": "10 years worldwide restriction"},
                    {"id": 2, "title": "Penalty", "text": "$1M penalty no cap"},
                ]
            }

        def risk_scorer(payload: dict) -> dict:
            # Return HIGH risk for both clauses
            return {
                "risk": {
                    "risk_level": "HIGH",
                    "confidence": "0.95",
                    "reason": "Overly broad restriction",
                    "flags": [
                        {"code": "NON_COMPETE", "description": "Excessive duration"},
                        {"code": "PENALTY", "description": "Unlimited liability"},
                    ],
                }
            }

        original_init(
            self,
            settings=settings,
            mcp_client=InMemoryMCPClient({"clause_extractor": clause_extractor, "risk_scorer": risk_scorer}),
        )

    monkeypatch.setattr(ToolRouter, "__init__", patched_init)

    exit_code = main.main()
    output = capsys.readouterr().out

    assert exit_code == 0
    payload = json.loads(output)

    # Verify session_id is valid UUID
    assert payload["session_id"]
    try:
        uuid.UUID(payload["session_id"])
    except ValueError:
        assert False, "session_id is not a valid UUID"

    # Verify HIGH risk clauses detected
    risk_results = payload.get("report_json", {}).get("risk_results", [])
    high_risk_count = sum(1 for r in risk_results if r.get("risk_level") == "HIGH")
    assert high_risk_count > 0, "Expected at least one HIGH risk clause"

    # Verify audit events count
    assert len(payload.get("audit_log", [])) > 10, "Expected more than 10 audit events"
