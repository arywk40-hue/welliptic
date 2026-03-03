"""Shared test fixtures for LexAudit tests."""

from __future__ import annotations

import pytest

from src.config import Settings
from src.tools.router import ToolRouter, ToolSpec


class InMemoryMCPClient:
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

    def call_tool(
        self,
        *,
        tool_name: str,
        method_name: str,
        payload: dict,
        timeout_seconds: float,
        tool_spec: ToolSpec,
    ) -> dict:
        if tool_name not in self.handlers:
            return {"ok": False, "error": f"tool {tool_name} not found"}
        data = self.handlers[tool_name](payload)
        if isinstance(data, dict) and "ok" in data:
            return data
        return {"ok": True, "data": data}


@pytest.fixture
def test_settings(tmp_path):
    """Settings configured for testing (no real API keys)."""
    return Settings(
        anthropic_api_key="",
        runs_dir=tmp_path,
        enforce_mcp=True,
        max_retries=1,
        retry_backoff_seconds=0.0,
    )


def make_happy_path_handlers():
    """Return clause_extractor + risk_scorer handlers for a LOW-risk scenario."""

    def clause_extractor(payload: dict) -> dict:
        return {
            "clauses": [
                {"id": 1, "title": "Services", "text": "Standard delivery terms"},
                {"id": 2, "title": "Payment", "text": "Invoice due in 30 days"},
            ]
        }

    def risk_scorer(payload: dict) -> dict:
        return {
            "risk": {
                "risk_level": "LOW",
                "confidence": "0.8",
                "reason": "Balanced clause",
                "flags": [],
            }
        }

    return {"clause_extractor": clause_extractor, "risk_scorer": risk_scorer}


def make_high_risk_handlers():
    """Return handlers where risk scoring returns HIGH risk."""

    def clause_extractor(payload: dict) -> dict:
        return {"clauses": [{"id": 1, "title": "Non-compete", "text": "10 years restriction"}]}

    def risk_scorer(payload: dict) -> dict:
        return {
            "risk": {
                "risk_level": "HIGH",
                "confidence": "0.9",
                "reason": "Overly broad restriction",
                "flags": [{"code": "non_compete", "description": "Long non-compete window"}],
            }
        }

    return {"clause_extractor": clause_extractor, "risk_scorer": risk_scorer}
