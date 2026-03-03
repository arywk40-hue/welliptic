from __future__ import annotations

from typing import Optional

from src.agent.control_loop import run_lexaudit
from src.config import Settings
from src.tools.router import ToolRouter
from src.types import AuditResult, DecisionProvider


def adk_available() -> bool:
    try:
        import google.adk  # type: ignore # noqa: F401

        return True
    except Exception:  # noqa: BLE001
        return False


def run_adk_workflow(
    contract_text: str,
    filename: str,
    *,
    max_steps: int = 50,
    human_gate_threshold: str = "HIGH",
    settings: Optional[Settings] = None,
    router: Optional[ToolRouter] = None,
    human_gate_enabled: bool = True,
    decision_provider: Optional[DecisionProvider] = None,
) -> AuditResult:
    # v1 uses a deterministic control loop while keeping an ADK-oriented entrypoint.
    return run_lexaudit(
        contract_text,
        filename,
        max_steps=max_steps,
        human_gate_threshold=human_gate_threshold,
        settings=settings,
        router=router,
        human_gate_enabled=human_gate_enabled,
        decision_provider=decision_provider,
    )
