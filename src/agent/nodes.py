"""LangGraph node functions for the alternative graph-based execution path.

These nodes wrap the same deterministic logic used by ``control_loop.py``
but are shaped for ``langgraph.graph.StateGraph`` consumption.

The primary execution path is ``control_loop.run_lexaudit()`` — these nodes
exist for the LangGraph demo variant in ``graph.py``.
"""

from __future__ import annotations

from typing import Any, Dict

from src.agent.state import AgentState
from src.applets.clause_extractor import extract_clauses_from_payload
from src.applets.risk_scorer import score_clause_from_payload
from src.types import Clause


# ── Node functions ────────────────────────────────────────────────────────


def ingest_node(state: AgentState) -> Dict[str, Any]:
    """Validate and normalize the incoming contract text."""
    text = state.get("contract_text", "")
    if not text.strip():
        return {**state, "fatal_error": True, "error_message": "Empty contract"}
    return {**state, "contract_text": text.strip(), "step_index": state.get("step_index", 0) + 1}


def extract_clauses_node(state: AgentState) -> Dict[str, Any]:
    """Extract clauses via the local deterministic parser."""
    contract_text = state.get("contract_text", "")
    clauses = extract_clauses_from_payload({"contract_text": contract_text})
    clause_dicts = [{"id": c.id, "title": c.title, "text": c.text} for c in clauses]
    return {
        **state,
        "clauses": clause_dicts,
        "current_clause_index": 0,
        "step_index": state.get("step_index", 0) + 1,
    }


def risk_score_node(state: AgentState) -> Dict[str, Any]:
    """Score the current clause's risk level."""
    clauses = state.get("clauses", [])
    idx = state.get("current_clause_index", 0)
    if idx >= len(clauses):
        return dict(state)

    clause_dict = clauses[idx]
    clause = Clause(id=clause_dict["id"], title=clause_dict["title"], text=clause_dict["text"])
    result = score_clause_from_payload(
        {"clause_text": clause.text, "clause_title": clause.title}, clause
    )
    risk_results = list(state.get("risk_results", []))
    risk_results.append({
        "clause_id": clause.id,
        "clause_title": clause.title,
        "risk_level": result.risk_level.value,
        "confidence": result.confidence,
        "reason": result.reason,
        "flags": result.flags,
    })
    return {
        **state,
        "risk_results": risk_results,
        "current_clause_index": idx + 1,
        "step_index": state.get("step_index", 0) + 1,
    }


def human_gate_node(state: AgentState) -> Dict[str, Any]:
    """Pause for human review (stub — actual decision comes externally)."""
    return {**state, "pending_human_review": True, "step_index": state.get("step_index", 0) + 1}


def generate_report_node(state: AgentState) -> Dict[str, Any]:
    """Generate the final summary report text."""
    risk_results = state.get("risk_results", [])
    high = [r for r in risk_results if r.get("risk_level") == "HIGH"]
    medium = [r for r in risk_results if r.get("risk_level") == "MEDIUM"]
    low = [r for r in risk_results if r.get("risk_level") == "LOW"]

    decision = state.get("human_decision", "auto")
    report = (
        f"LEXAUDIT REPORT\n"
        f"Decision: {decision}\n"
        f"HIGH: {len(high)} | MEDIUM: {len(medium)} | LOW: {len(low)}\n"
        f"Total clauses: {len(state.get('clauses', []))}\n"
    )
    return {
        **state,
        "report_text": report,
        "terminate_reason": "REPORT_COMPLETE",
        "step_index": state.get("step_index", 0) + 1,
    }
