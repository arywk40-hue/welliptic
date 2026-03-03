"""Tests for the local fallback MCP client (deterministic, same as WASM applets)."""

from __future__ import annotations

import pytest

from src.agent.control_loop import run_lexaudit
from src.config import Settings
from src.tools.local_fallback import (
    LocalFallbackMCPClient,
    _is_clause_header,
    _score_single,
    _split_contract,
)
from src.tools.router import ToolRouter, ToolSpec

SAMPLE_NDA = """1. Confidentiality
The Receiving Party agrees to keep all Confidential Information strictly confidential
and shall not disclose it to any third party without prior written consent.

2. Non-Compete
For a period of 10 years worldwide, the Receiving Party shall not engage in any
business that competes with the Disclosing Party. This is irrevocable and perpetual.

3. Indemnification
The Receiving Party shall indemnify and hold harmless the Disclosing Party from
any claims arising from breach of this Agreement, with no liability cap.

4. Term
This Agreement shall remain in effect for 2 years from the Effective Date
and may be renewed by mutual written agreement.
"""


def test_clause_header_detection():
    assert _is_clause_header("1. Confidentiality")
    assert _is_clause_header("2) Non-Compete")
    assert _is_clause_header("§3. Indemnification")
    assert not _is_clause_header("This is a regular line")
    assert not _is_clause_header("")
    assert not _is_clause_header("   ")


def test_split_contract_numbered():
    clauses = _split_contract(SAMPLE_NDA)
    assert len(clauses) == 4
    assert clauses[0]["id"] == 1
    assert clauses[0]["title"] == "Confidentiality"
    assert "strictly confidential" in clauses[0]["text"]


def test_split_contract_fallback():
    clauses = _split_contract("This is a plain contract with no numbered clauses.")
    assert len(clauses) == 1
    assert clauses[0]["title"] == "Full Contract"


def test_risk_scoring_high():
    result = _score_single(2, "Non-Compete", "worldwide irrevocable perpetual restriction")
    assert result["risk_level"] == "HIGH"
    assert float(result["confidence"]) >= 0.75
    assert len(result["flags"]) >= 2


def test_risk_scoring_medium():
    result = _score_single(3, "Indemnification", "shall indemnify the party for any penalty")
    assert result["risk_level"] == "MEDIUM"
    assert len(result["flags"]) >= 1


def test_risk_scoring_low():
    result = _score_single(4, "Term", "Agreement valid for 2 years with mutual renewal.")
    assert result["risk_level"] == "LOW"
    assert float(result["confidence"]) >= 0.8
    assert len(result["flags"]) == 0


def test_local_fallback_client_clause_extractor():
    specs = {
        "clause_extractor": ToolSpec(applet_id="local", interface="ClauseExtractor", default_method="extract_clauses"),
        "risk_scorer": ToolSpec(applet_id="local", interface="RiskScorer", default_method="score_clause_risk"),
    }
    client = LocalFallbackMCPClient(tool_specs=specs)
    assert client.is_available()

    result = client.call_tool(
        tool_name="clause_extractor",
        method_name="extract_clauses",
        payload={"contract_text": SAMPLE_NDA},
        timeout_seconds=10,
        tool_spec=specs["clause_extractor"],
    )
    assert result["ok"] is True
    clauses = result["result"]["Ok"]
    assert len(clauses) == 4


def test_local_fallback_client_risk_scorer():
    specs = {
        "clause_extractor": ToolSpec(applet_id="local", interface="ClauseExtractor", default_method="extract_clauses"),
        "risk_scorer": ToolSpec(applet_id="local", interface="RiskScorer", default_method="score_clause_risk"),
    }
    client = LocalFallbackMCPClient(tool_specs=specs)

    result = client.call_tool(
        tool_name="risk_scorer",
        method_name="score_clause_risk",
        payload={
            "clause_id": 2,
            "clause_title": "Non-Compete",
            "clause_text": "worldwide irrevocable perpetual restriction",
        },
        timeout_seconds=10,
        tool_spec=specs["risk_scorer"],
    )
    assert result["ok"] is True
    risk = result["result"]["Ok"]
    assert risk["risk_level"] == "HIGH"


def test_full_pipeline_with_local_fallback(tmp_path):
    """End-to-end pipeline using the local fallback client (no SDK needed)."""
    settings = Settings(
        anthropic_api_key="",
        runs_dir=tmp_path,
        enforce_mcp=True,
        max_retries=1,
        retry_backoff_seconds=0.0,
    )
    specs = {
        "clause_extractor": ToolSpec(
            applet_id="local",
            interface="ClauseExtractor",
            default_method="extract_clauses",
        ),
        "risk_scorer": ToolSpec(
            applet_id="local",
            interface="RiskScorer",
            default_method="score_clause_risk",
        ),
    }
    client = LocalFallbackMCPClient(tool_specs=specs)
    router = ToolRouter(settings=settings, mcp_client=client)

    result = run_lexaudit(
        contract_text=SAMPLE_NDA,
        filename="sample_nda.txt",
        settings=settings,
        router=router,
        human_gate_enabled=True,
        decision_provider=None,
    )

    # Should extract 4 clauses
    assert len(result.state.clauses) == 4
    # Should have risk results for all 4 clauses
    assert len(result.state.risk_results) == 4
    # Clause 2 (Non-Compete) should be HIGH risk (worldwide, irrevocable, perpetual)
    non_compete = [r for r in result.state.risk_results if r.clause_id == 2]
    assert len(non_compete) == 1
    assert non_compete[0].risk_level.value == "HIGH"
    # Should trigger human gate since there are HIGH risk clauses
    assert result.pending_human_review is True
    assert result.state.human_decision == "pending"
    # Audit events should be populated
    assert len(result.audit_log) > 10
