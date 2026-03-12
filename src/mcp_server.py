"""LexAudit MCP Server — Weilchain-secured MCP tool endpoints.

Hosts the ClauseExtractor and RiskScorer as proper MCP tools using FastMCP,
secured with ``weil_middleware()`` (wallet-signature verification on every
request) and ``@secured()`` (on-chain access-control via ``key_has_purpose``).

This is the **canonical Weilchain MCP integration** — the same pattern used in
the SDK examples (``wadk-sdk/adk/python/examples/mcp_server.py``):

    FastMCP server
      + @secured("svc_name")    → on-chain access control per tool
      + weil_middleware()        → wallet-signature verification per request
      + streamable-http transport

Usage::

    # Start the MCP server (port 8001)
    python -m src.mcp_server

    # Or from main entry point
    python main.py --serve-mcp

The LexAudit agent connects to this server using signed auth headers::

    headers = agent.get_auth_headers()  # from WeilAgent
    async with streamablehttp_client("http://localhost:8001/mcp", headers=headers):
        ...
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import uvicorn
from dotenv import load_dotenv
from fastmcp import FastMCP

load_dotenv()

logger = logging.getLogger(__name__)

# ── FastMCP server ────────────────────────────────────────────────────────

mcp = FastMCP("lexaudit-mcp", instructions=(
    "LexAudit MCP server providing legal contract clause extraction and "
    "risk scoring tools, secured by Weilchain wallet verification."
))


# ── Weilchain-secured tools ──────────────────────────────────────────────

# Import the SDK's @secured decorator for on-chain access control.
# Falls back to a no-op decorator if the SDK is not installed.
try:
    from weil_ai.mcp import secured as _secured
    _HAS_SECURED = True
except ImportError:
    _HAS_SECURED = False

    def _secured(svc_name: str):  # type: ignore[misc]
        """No-op fallback when weil_ai is not installed."""
        def decorator(func):  # type: ignore[no-untyped-def]
            return func
        return decorator


# Service names for on-chain access control.
# These map to deployed applets on Weilchain via get_applet_id_for_name().
CLAUSE_EXTRACTOR_SVC = os.getenv("CLAUSE_EXTRACTOR_SVC_NAME", "lexaudit::clause_extractor")
RISK_SCORER_SVC = os.getenv("RISK_SCORER_SVC_NAME", "lexaudit::risk_scorer")


@mcp.tool()
@_secured(CLAUSE_EXTRACTOR_SVC)
async def extract_clauses(contract_text: str) -> str:
    """Extract all distinct clauses from a legal contract.

    Reads the raw contract text and identifies individual clauses with
    structure: id, title, and body text. Returns a JSON array of clauses.

    This tool is secured by Weilchain — the caller's wallet must have
    'Execution' purpose on the ClauseExtractor applet.
    """
    # Try LLM-powered extraction first (same quality as the main agent)
    try:
        from src.applets.clause_extractor import extract_clauses as llm_extract
        from src.types import ToolContext

        ctx = ToolContext(
            session_id="mcp-server",
            model=os.getenv("ANTHROPIC_MODEL", "claude-opus-4-1"),
            prompt_template_id="mcp_clause_extract",
        )
        clauses = llm_extract(contract_text, ctx)
        return json.dumps([{"id": c.id, "title": c.title, "text": c.text} for c in clauses])
    except Exception:
        pass

    # Fallback: deterministic split (mirrors the on-chain WASM applet)
    try:
        from src.tools.local_fallback import _split_contract
        clauses = _split_contract(contract_text)
        return json.dumps(clauses)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool()
@_secured(RISK_SCORER_SVC)
async def score_clause_risk(clause_id: int, clause_title: str, clause_text: str) -> str:
    """Score a single legal clause for risk level (HIGH / MEDIUM / LOW).

    Analyzes the clause text and returns a JSON object with risk_level,
    confidence, reason, and flags.

    This tool is secured by Weilchain — the caller's wallet must have
    'Execution' purpose on the RiskScorer applet.
    """
    # Try LLM-powered scoring first
    try:
        from src.applets.risk_scorer import score_clause_risk as llm_score
        from src.types import Clause, ToolContext

        ctx = ToolContext(
            session_id="mcp-server",
            model=os.getenv("ANTHROPIC_MODEL", "claude-opus-4-1"),
            prompt_template_id="mcp_risk_score",
        )
        clause = Clause(id=clause_id, title=clause_title, text=clause_text)
        risk = llm_score(clause, ctx)
        return json.dumps({
            "risk_level": risk.risk_level.value,
            "confidence": risk.confidence,
            "reason": risk.reason,
            "flags": [
                {
                    "code": f.split(":")[0].strip(),
                    "description": f.split(":", 1)[1].strip() if ":" in f else f,
                }
                for f in risk.flags
            ],
        })
    except Exception:
        pass

    # Fallback: deterministic keyword scoring (mirrors the on-chain WASM applet)
    try:
        from src.tools.local_fallback import _score_single
        result = _score_single(clause_id, clause_title, clause_text)
        return json.dumps(result)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


# ── Build the Starlette/ASGI app with weil_middleware ─────────────────────

app = mcp.http_app(transport="streamable-http")

# Mount weil_middleware() — this verifies wallet signatures on every POST
# request, just like the SDK example (wadk-sdk/adk/python/examples/mcp_server.py).
try:
    from weil_ai.mcp import weil_middleware
    app.add_middleware(weil_middleware())
    logger.info("✅ weil_middleware() mounted — wallet signatures verified on all POST requests")
except ImportError:
    logger.warning("⚠️ weil_ai not installed — MCP server running without wallet verification")


if __name__ == "__main__":
    port = int(os.getenv("MCP_SERVER_PORT", "8001"))
    print(f"🔗 LexAudit MCP Server starting on http://0.0.0.0:{port}/mcp")
    print(f"   Transport: streamable-http")
    print(f"   Weil secured: {_HAS_SECURED}")
    print(f"   Tools: extract_clauses, score_clause_risk")
    uvicorn.run(app, host="0.0.0.0", port=port)
