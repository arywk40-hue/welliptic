from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import List

from dotenv import load_dotenv

# Ensure local `src` package is importable for both script and module execution.
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.agent.adk_workflow import run_adk_workflow
from src.config import load_settings
from src.tools.router import McpUnavailableError, ToolRouter
from src.types import RiskScore


def _load_text(input_arg: str) -> tuple[str, str]:
    """Load contract text from a file path or stdin. Input is required."""
    if input_arg == "-":
        return sys.stdin.read(), "stdin.txt"
    if not input_arg:
        raise ValueError("--input is required: provide a contract file path or '-' for stdin")
    path = Path(input_arg)
    if not path.exists():
        raise FileNotFoundError(f"Contract file not found: {path}")
    return path.read_text(encoding="utf-8"), path.name


def _interactive_decision(risks: List[RiskScore]) -> str:
    print("\nHUMAN REVIEW REQUIRED")
    for item in risks:
        print(f"- [{item.clause_title}] {item.reason}")
    decision = input("Approve contract? (approve/reject): ").strip().lower()
    if decision not in {"approve", "reject"}:
        return "reject"
    return decision


def main() -> int:
    parser = argparse.ArgumentParser(description="LexAudit v1 (ADK-oriented loop + MCP tools)")
    parser.add_argument("--serve", action="store_true", help="Start FastAPI server on port 8000")
    parser.add_argument("--serve-mcp", action="store_true",
                        help="Start Weilchain-secured MCP server on port 8001")
    parser.add_argument("--input", default="", help="Contract file path (required) or '-' for stdin")
    parser.add_argument("--format", default="text", choices=["text", "json"])
    parser.add_argument("--max-steps", type=int, default=50)
    parser.add_argument("--human-gate-threshold", default="HIGH", choices=["LOW", "MEDIUM", "HIGH"])
    parser.add_argument("--no-human-gate", action="store_true")
    args = parser.parse_args()

    load_dotenv()

    if args.serve_mcp:
        # Launch the Weilchain-secured MCP server (FastMCP + @secured + weil_middleware)
        import uvicorn
        from src.mcp_server import app as mcp_app

        port = int(os.getenv("MCP_SERVER_PORT", "8001"))
        print(f"🔗 LexAudit MCP Server starting on http://0.0.0.0:{port}/mcp")
        uvicorn.run(mcp_app, host="0.0.0.0", port=port)
        return 0

    if args.serve:
        import uvicorn

        uvicorn.run("src.api.server:app", host="0.0.0.0", port=8000, reload=False)
        return 0

    settings = load_settings()

    try:
        contract_text, filename = _load_text(args.input)
    except Exception as exc:  # noqa: BLE001
        print(f"Failed to load input: {exc}", file=sys.stderr)
        return 2

    try:
        router = ToolRouter(settings=settings)
    except McpUnavailableError as exc:
        print(f"MCP bootstrap failed: {exc}", file=sys.stderr)
        return 1

    try:
        result = run_adk_workflow(
            contract_text,
            filename,
            max_steps=args.max_steps,
            human_gate_threshold=args.human_gate_threshold,
            settings=settings,
            router=router,
            human_gate_enabled=not args.no_human_gate,
            decision_provider=_interactive_decision if not args.no_human_gate else None,
        )
    except McpUnavailableError as exc:
        print(f"MCP unavailable: {exc}", file=sys.stderr)
        return 1

    if args.format == "json":
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=True))
    else:
        print(result.report_text or "")
        print(f"Session: {result.session_id}")
        print(f"Audit events: {len(result.audit_log)}")

    if result.state.fatal_error:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
