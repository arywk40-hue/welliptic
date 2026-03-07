"""
Run this once real Weilchain env vars are set to verify
the full pipeline with real MCP.

Usage: python scripts/verify_real_mcp.py <contract_file>
"""

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

REQUIRED_VARS = [
    "WEILCHAIN_NODE_URL",
    "CLAUSE_EXTRACTOR_APPLET_ID",
    "RISK_SCORER_APPLET_ID",
]

# At least one LLM provider must be configured
LLM_GROUPS = [
    ("USE_GROQ", "GROQ_API_KEY"),
    ("USE_GEMINI", "GEMINI_API_KEY"),
    ("USE_OPENAI", "OPENAI_API_KEY"),
    ("ANTHROPIC_API_KEY",),
]


def check_env() -> None:
    missing = [v for v in REQUIRED_VARS if not os.getenv(v)]
    if missing:
        print(f"Missing env vars: {missing}")
        print("Set these in .env before running real MCP verification")
        sys.exit(1)

    # Check that at least one LLM provider is configured
    has_llm = False
    for group in LLM_GROUPS:
        if len(group) == 1:
            if os.getenv(group[0]):
                has_llm = True
                break
        else:
            flag, key = group
            if os.getenv(flag, "").lower() in {"1", "true", "yes"} and os.getenv(key):
                has_llm = True
                break
    if not has_llm:
        print("WARNING: No LLM provider configured — will use deterministic fallback")
    else:
        print("LLM provider: configured ✓")

    print("All env vars present")


def run_verification() -> None:
    if len(sys.argv) < 2:
        print("Usage: python scripts/verify_real_mcp.py <contract_file>")
        print("Provide a real contract file to verify MCP pipeline")
        sys.exit(1)

    contract_path = Path(sys.argv[1])
    if not contract_path.exists():
        print(f"Contract file not found: {contract_path}")
        sys.exit(1)

    contract_text = contract_path.read_text(encoding="utf-8")
    filename = contract_path.name

    check_env()
    print(f"\nRunning real MCP verification with: {filename}")
    print()

    from src.agent.control_loop import run_lexaudit
    from src.config import load_settings
    from src.tools.router import ToolRouter

    settings = load_settings()
    router = ToolRouter(settings=settings)

    result = run_lexaudit(
        contract_text=contract_text,
        filename=filename,
        max_steps=20,
        human_gate_threshold="HIGH",
        settings=settings,
        router=router,
    )

    print(f"Session: {result.session_id}")
    print(f"Clauses found: {len(result.clauses)}")
    print(f"Audit events: {len(result.audit_events)}")
    high = [r for r in result.risk_scores if r.risk_level.value == "HIGH"]
    print(f"HIGH risk clauses: {len(high)}")
    print(json.dumps(result.report_json.get("summary", {}), indent=2))

    if len(result.clauses) >= 1:
        print("\nREAL MCP VERIFICATION PASSED")
    else:
        print("\nVERIFICATION FAILED - check applet responses")
        sys.exit(1)


if __name__ == "__main__":
    run_verification()
