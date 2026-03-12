# src/agent/graph.py
from __future__ import annotations

from typing import Any

from langgraph.graph import StateGraph, END
from src.agent.state import AgentState
from src.agent.nodes import (
    ingest_node, extract_clauses_node,
    risk_score_node, human_gate_node, generate_report_node
)

def should_continue_scoring(state: AgentState) -> str:
    """Route after each clause is scored."""
    if state["fatal_error"]:
        return "terminate"
    if state["step_index"] >= state["max_steps"]:
        print("⚠️  Max steps reached — terminating")
        return "terminate"
    if state["current_clause_index"] >= len(state["clauses"]):
        # All clauses scored — check if any HIGH risk
        high = [r for r in state["risk_results"]
                if r["risk_level"] == "HIGH"]
        if high:
            return "human_gate"
        return "report"
    return "continue_scoring"

def build_graph() -> Any:
    g = StateGraph(AgentState)

    # Add all nodes
    g.add_node("ingest",         ingest_node)
    g.add_node("extract_clauses",extract_clauses_node)
    g.add_node("risk_score",     risk_score_node)
    g.add_node("human_gate",     human_gate_node)
    g.add_node("generate_report",generate_report_node)

    # Entry point
    g.set_entry_point("ingest")

    # Fixed edges
    g.add_edge("ingest",          "extract_clauses")
    g.add_edge("extract_clauses", "risk_score")
    g.add_edge("human_gate",      "generate_report")
    g.add_edge("generate_report", END)

    # Conditional routing after each clause scored
    g.add_conditional_edges(
        "risk_score",
        should_continue_scoring,
        {
            "continue_scoring": "risk_score",
            "human_gate":       "human_gate",
            "report":           "generate_report",
            "terminate":        END
        }
    )
    return g.compile()