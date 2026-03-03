from __future__ import annotations

import json
from pathlib import Path

import main
from src.tools.router import ToolRouter, ToolSpec


class _InMemoryMCPClient:
    """Test-only mock that mimics MCP tool dispatch in memory."""

    def __init__(self, handlers: dict) -> None:
        self.handlers = handlers

    def is_available(self) -> bool:
        return True

    def discover_tools(self) -> dict:
        return {
            name: ToolSpec(applet_id=name, interface="InMemory", default_method=name)
            for name in self.handlers
        }

    def call_tool(self, *, tool_name: str, method_name: str, payload: dict,
                  timeout_seconds: float, tool_spec: ToolSpec) -> dict:
        if tool_name not in self.handlers:
            return {"ok": False, "error": f"tool {tool_name} not found"}
        data = self.handlers[tool_name](payload)
        if isinstance(data, dict) and "ok" in data:
            return data
        return {"ok": True, "data": data}


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
            mcp_client=_InMemoryMCPClient({"clause_extractor": clause_extractor, "risk_scorer": risk_scorer}),
        )

    monkeypatch.setattr(ToolRouter, "__init__", patched_init)

    exit_code = main.main()
    output = capsys.readouterr().out

    assert exit_code == 0
    payload = json.loads(output)
    assert payload["session_id"]
    assert "audit_log" in payload
