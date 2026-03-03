"""
Node function stubs for future LangGraph / Google ADK integration.

In the current v1 implementation, all node logic lives directly in
``src/agent/control_loop.py`` as a deterministic state machine.

If you migrate to LangGraph, extract each step (ingest, extract_clauses,
risk_score, human_gate, terminate) into standalone node functions here
and wire them into a ``StateGraph``.

Example (LangGraph):

    from langgraph.graph import StateGraph
    from src.types import AgentState

    graph = StateGraph(AgentState)
    graph.add_node("ingest", node_ingest)
    graph.add_node("extract_clauses", node_extract_clauses)
    graph.add_node("risk_score", node_risk_score)
    graph.add_node("human_gate", node_human_gate)
    graph.add_node("terminate", node_terminate)

    graph.set_entry_point("ingest")
    graph.add_edge("ingest", "extract_clauses")
    graph.add_edge("extract_clauses", "risk_score")
    graph.add_conditional_edges("risk_score", ...)
"""

from __future__ import annotations
