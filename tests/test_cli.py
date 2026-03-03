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
