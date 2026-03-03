from __future__ import annotations

import pytest

from src.agent.control_loop import run_lexaudit
from src.config import Settings
from src.tools.router import McpUnavailableError, ToolRouter, ToolSpec
from tests.conftest import InMemoryMCPClient, make_happy_path_handlers, make_high_risk_handlers


def _settings(tmp_path):
    return Settings(
        anthropic_api_key="",
        runs_dir=tmp_path,
        enforce_mcp=True,
        max_retries=1,
        retry_backoff_seconds=0.0,
    )


def test_happy_path_auto_approve(tmp_path) -> None:
    handlers = make_happy_path_handlers()
    router = ToolRouter(
        settings=_settings(tmp_path),
        mcp_client=InMemoryMCPClient(handlers),
    )

    result = run_lexaudit(
        "Contract text",
        "contract.txt",
        settings=_settings(tmp_path),
        router=router,
    )

    assert not result.state.fatal_error
    assert result.state.human_decision == "auto-approved"
    assert result.report_json["summary"]["low"] == 2


def test_human_gate_pending_when_high_risk(tmp_path) -> None:
    handlers = make_high_risk_handlers()
    router = ToolRouter(
        settings=_settings(tmp_path),
        mcp_client=InMemoryMCPClient(handlers),
    )

    result = run_lexaudit(
        "Contract text",
        "contract.txt",
        settings=_settings(tmp_path),
        router=router,
        decision_provider=None,
    )

    assert result.pending_human_review
    assert result.state.human_decision == "pending"
    assert result.state.terminate_reason == "HUMAN_REVIEW_PENDING"


def test_mcp_unavailable_fail_closed(tmp_path) -> None:
    class _UnavailableClient:
        def is_available(self) -> bool:
            return False

        def discover_tools(self) -> dict:
            return {}

        def call_tool(self, *, tool_name: str, method_name: str, payload: dict,
                      timeout_seconds: float, tool_spec: ToolSpec) -> dict:
            raise RuntimeError("unreachable")

    router = ToolRouter(settings=_settings(tmp_path), mcp_client=_UnavailableClient())
    with pytest.raises(McpUnavailableError):
        run_lexaudit(
            "Contract text",
            "contract.txt",
            settings=_settings(tmp_path),
            router=router,
            human_gate_enabled=False,
        )


def test_parse_retry_then_fail(tmp_path) -> None:
    def clause_extractor(payload: dict) -> dict:
        return {"clauses": [{"id": 1, "title": "Clause", "text": "X"}]}

    def risk_scorer(payload: dict) -> dict:
        return {
            "risk": {
                "risk_level": "CRITICAL",
                "confidence": "0.2",
                "reason": "invalid",
                "flags": [],
            }
        }

    router = ToolRouter(
        settings=_settings(tmp_path),
        mcp_client=InMemoryMCPClient({"clause_extractor": clause_extractor, "risk_scorer": risk_scorer}),
    )

    result = run_lexaudit(
        "Contract text",
        "contract.txt",
        settings=_settings(tmp_path),
        router=router,
        human_gate_enabled=False,
    )

    assert result.state.fatal_error
    assert result.state.terminate_reason == "INVALID_TOOL_OUTPUT"
