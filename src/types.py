from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Literal, Optional


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


HumanDecision = Literal["approve", "reject", "auto-approved", "pending"]


@dataclass
class Clause:
    id: int
    title: str
    text: str


@dataclass
class RiskScore:
    clause_id: int
    clause_title: str
    risk_level: RiskLevel
    confidence: float
    reason: str
    flags: List[str] = field(default_factory=list)


@dataclass
class ToolContext:
    session_id: str
    model: str
    prompt_template_id: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolResult:
    success: bool
    data: Optional[Dict[str, Any]]
    error: Optional[str]
    attempts: int
    latency_ms: int
    raw: Optional[Any] = None


@dataclass
class AgentState:
    contract_text: str
    filename: str
    clauses: List[Clause] = field(default_factory=list)
    current_clause_index: int = 0
    risk_results: List[RiskScore] = field(default_factory=list)
    step_index: int = 0
    max_steps: int = 50
    fatal_error: bool = False
    error_message: Optional[str] = None
    human_gate_open: bool = False
    human_decision: Optional[HumanDecision] = None
    final_report: Optional[str] = None
    session_id: Optional[str] = None
    terminate_reason: Optional[str] = None


@dataclass
class AuditEvent:
    step_index: int
    event_type: str
    timestamp: int
    node: str
    input_hash: Optional[str]
    output_hash: Optional[str]
    latency_ms: int
    model: Optional[str]
    tool_name: Optional[str]
    status: str
    error: Optional[str]
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AuditResult:
    session_id: str
    state: AgentState
    audit_log: List[AuditEvent]
    report_text: Optional[str]
    report_json: Dict[str, Any]
    pending_human_review: bool
    weil_audit_logger: Optional[Any] = None  # WeilAuditLogger, avoid circular import
    final_tx_hash: Optional[str] = None

    @property
    def clauses(self) -> List[Clause]:
        return self.state.clauses

    @property
    def audit_events(self) -> List[AuditEvent]:
        return self.audit_log

    @property
    def risk_scores(self) -> List[RiskScore]:
        return self.state.risk_results

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "session_id": self.session_id,
            "state": asdict(self.state),
            "audit_log": [asdict(e) for e in self.audit_log],
            "report_text": self.report_text,
            "report_json": self.report_json,
            "pending_human_review": self.pending_human_review,
            # Expose the final on-chain tx_hash at the top level so the UI
            # can display it directly without scanning the audit_log events.
            "tx_hash": self.final_tx_hash,
        }
        # Also include all tx_hashes from individual audit events
        if self.weil_audit_logger and hasattr(self.weil_audit_logger, 'get_tx_hashes'):
            result["tx_hashes"] = self.weil_audit_logger.get_tx_hashes()
        return result


DecisionProvider = Callable[[List[RiskScore]], str]
