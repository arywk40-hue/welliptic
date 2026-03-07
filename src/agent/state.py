# src/agent/state.py
from typing import TypedDict, List, Optional, Any

class AgentState(TypedDict):
    # Input
    contract_text: str
    filename: str

    # Processing
    clauses: List[dict]           # extracted clauses
    current_clause_index: int     # which clause we're on
    risk_results: List[dict]      # scored results

    # Control flow
    step_index: int               # monotonic counter
    max_steps: int                # safety cutoff (default 50)
    fatal_error: bool             # kills the loop
    error_message: Optional[str]

    # Human-in-the-loop
    human_gate_open: bool         # True = agent is paused
    human_decision: Optional[str] # "approve" or "reject"

    # Output
    final_report: Optional[str]
    session_id: Optional[str]     # Weilchain session (added at deploy)
    audit_log: List[dict]         # local log for now, on-chain at deploy