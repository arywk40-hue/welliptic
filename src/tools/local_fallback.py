"""Local fallback MCP client — runs the same deterministic logic as the WASM applets.

When the Weilchain Sentinel or SDK is unreachable, this client executes the
same clause-extraction and risk-scoring algorithms that the on-chain Rust
applets use, so the full pipeline still works end-to-end.

**LLM-enhanced mode**: When a real LLM (Groq / Gemini / OpenAI) is available
(detected via env vars), the local client delegates to the AI-powered
``extract_clauses()`` and ``score_clause_risk()`` functions, producing
genuine AI-driven analysis instead of keyword heuristics.

The deterministic logic mirrors ``rust_applets/clause_extractor/src/lib.rs``
and ``rust_applets/risk_scorer/src/lib.rs`` exactly and is used as the
ultimate fallback when *no* LLM provider is reachable:

- Clause extraction: header-based structural splitting (numbered lines).
- Risk scoring: keyword-based classification with HIGH/MEDIUM keyword lists.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

from src.tools.router import ToolSpec

logger = logging.getLogger(__name__)


# ── Clause Extraction (mirrors clause_extractor/src/lib.rs) ──────────────


def _is_clause_header(line: str) -> bool:
    """Check if a line looks like a top-level numbered clause header (e.g. '1. ...', '§2)').

    Subsection headers like '1.1', '2.3' are NOT treated as top-level headers.
    """
    trimmed = line.strip()
    if not trimmed:
        return False

    # Handle § prefix
    if trimmed.startswith("§"):
        rest = trimmed[1:]
        has_digit = False
        for ch in rest:
            if ch.isdigit():
                has_digit = True
                continue
            return has_digit and ch in ".) \t"
        return False

    # Standard numbered header — must be a simple number (not subsection like 1.1)
    i = 0
    while i < len(trimmed) and trimmed[i].isdigit():
        i += 1
    if i == 0:
        return False
    if i < len(trimmed) and trimmed[i] in ")\t":
        return True
    # For dot notation: '1.' is a header, '1.1' is a subsection
    if i < len(trimmed) and trimmed[i] == ".":
        # Check what follows the dot
        if i + 1 < len(trimmed) and trimmed[i + 1].isdigit():
            return False  # subsection like '1.1', '2.3'
        return True  # top-level like '1. DEFINITIONS'
    return False


def _parse_header_id(header: str, fallback: int) -> int:
    """Extract numeric ID from a clause header."""
    trimmed = header.strip().lstrip("§")
    digits = ""
    for ch in trimmed:
        if ch.isdigit():
            digits += ch
        elif digits:
            break
    try:
        return int(digits)
    except ValueError:
        return fallback


def _parse_header_title(header: str) -> str:
    """Extract title text from a clause header, stripping the number prefix."""
    trimmed = header.strip()
    i = 0
    if trimmed.startswith("§"):
        i = 1
    while i < len(trimmed) and trimmed[i].isdigit():
        i += 1
    while i < len(trimmed) and trimmed[i] in ".):-  \t":
        i += 1
    title = trimmed[i:].strip()
    return title if title else "Untitled Clause"


def _split_contract(text: str) -> List[Dict[str, Any]]:
    """Split contract text into clauses using header detection."""
    clauses: List[Dict[str, Any]] = []
    cur_header: str | None = None
    cur_body: List[str] = []

    def flush() -> None:
        if cur_header is not None:
            next_id = len(clauses) + 1
            cid = _parse_header_id(cur_header, next_id)
            title = _parse_header_title(cur_header)
            body_text = "\n".join(cur_body).strip()
            if body_text:
                clauses.append({"id": cid, "title": title, "text": body_text})

    for line in text.splitlines():
        if _is_clause_header(line):
            flush()
            cur_header = line.strip()
            cur_body = []
        elif cur_header is not None:
            cur_body.append(line)

    flush()

    # Fallback: entire text as one clause
    if not clauses and text.strip():
        clauses.append({"id": 1, "title": "Full Contract", "text": text.strip()})

    return clauses


# ── Risk Scoring (mirrors risk_scorer/src/lib.rs) ────────────────────────

HIGH_KEYWORDS = [
    ("unlimited", "UNLIMITED_OBLIGATION"),
    ("irrevocable", "IRREVOCABLE_TERM"),
    ("worldwide", "WORLDWIDE_SCOPE"),
    ("no liability", "NO_LIABILITY_RECOURSE"),
    ("perpetual", "PERPETUAL_TERM"),
    ("waive all", "WAIVER_OF_RIGHTS"),
]

MEDIUM_KEYWORDS = [
    ("penalty", "PENALTY_CLAUSE"),
    ("indemnify", "INDEMNITY_OBLIGATION"),
    ("exclusive", "EXCLUSIVITY_RESTRICTION"),
    ("non-compete", "NON_COMPETE_RESTRICTION"),
    ("confidential", "CONFIDENTIALITY_CONSTRAINT"),
    ("automatic renewal", "AUTO_RENEWAL_RISK"),
    ("termination fee", "TERMINATION_FEE"),
]


def _score_single(clause_id: int, clause_title: str, clause_text: str) -> Dict[str, Any]:
    """Score a single clause using keyword-based risk classification."""
    lower = clause_text.lower()
    flags: List[Dict[str, str]] = []
    high_count = 0
    medium_count = 0

    for kw, code in HIGH_KEYWORDS:
        if kw in lower:
            high_count += 1
            flags.append({"code": code, "description": f"Contains '{kw}'"})

    for kw, code in MEDIUM_KEYWORDS:
        if kw in lower:
            medium_count += 1
            flags.append({"code": code, "description": f"Contains '{kw}'"})

    if high_count >= 2:
        risk_level, confidence = "HIGH", "0.90"
    elif high_count == 1:
        risk_level, confidence = "HIGH", "0.75"
    elif medium_count >= 2:
        risk_level, confidence = "MEDIUM", "0.80"
    elif medium_count == 1:
        risk_level, confidence = "MEDIUM", "0.65"
    else:
        risk_level, confidence = "LOW", "0.85"

    if not flags:
        reason = "No significant risk indicators detected"
    else:
        codes = [f["code"] for f in flags]
        reason = f"Found {len(flags)} risk indicator(s): {', '.join(codes)}"

    return {
        "clause_id": clause_id,
        "clause_title": clause_title,
        "risk_level": risk_level,
        "confidence": confidence,
        "reason": reason,
        "flags": flags,
    }


# ── LLM availability probe ────────────────────────────────────────────────


def _llm_available() -> bool:
    """Return True when at least one LLM provider has valid config.

    Checked in priority order: Groq > Gemini > OpenAI > Anthropic.
    """
    if os.getenv("USE_GROQ", "").lower() in {"1", "true", "yes"} and os.getenv("GROQ_API_KEY"):
        return True
    if os.getenv("USE_GEMINI", "").lower() in {"1", "true", "yes"} and os.getenv("GEMINI_API_KEY"):
        return True
    if os.getenv("USE_OPENAI", "").lower() in {"1", "true", "yes"} and os.getenv("OPENAI_API_KEY"):
        return True
    if os.getenv("ANTHROPIC_API_KEY"):
        return True
    return False


# ── MCP Client ───────────────────────────────────────────────────────────


class LocalFallbackMCPClient:
    """Deterministic local MCP client that mirrors the on-chain WASM applets.

    When a real LLM is available (Groq / Gemini / OpenAI / Anthropic), this
    client **delegates** to the AI-powered extraction and scoring functions,
    producing the same quality output as if the Weilchain Sentinel were
    reachable.  When no LLM is configured it falls back to the deterministic
    keyword/header heuristics that mirror the deployed Rust contracts.
    """

    def __init__(self, tool_specs: Dict[str, ToolSpec]) -> None:
        self._tool_specs = tool_specs

    def is_available(self) -> bool:
        return True

    def discover_tools(self) -> Dict[str, ToolSpec]:
        return dict(self._tool_specs)

    def call_tool(
        self,
        *,
        tool_name: str,
        method_name: str,
        payload: Dict[str, Any],
        timeout_seconds: float,
        tool_spec: ToolSpec,
    ) -> Dict[str, Any]:
        if tool_name == "clause_extractor":
            return self._handle_clause_extractor(method_name, payload)
        elif tool_name == "risk_scorer":
            return self._handle_risk_scorer(method_name, payload)
        else:
            return {"ok": False, "error": f"Unknown tool: {tool_name}"}

    # ── Clause Extraction ────────────────────────────────────────────────

    def _handle_clause_extractor(self, method: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        contract_text = payload.get("contract_text", "")
        if not contract_text.strip():
            return {"ok": False, "error": "contract_text cannot be empty"}

        if method == "extract_clauses":
            # Try real LLM first
            if _llm_available():
                try:
                    return self._llm_extract_clauses(contract_text)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("LLM clause extraction failed (%s) — falling back to deterministic", exc)
            clauses = _split_contract(contract_text)
            return {"ok": True, "result": {"Ok": clauses}}
        elif method == "count_clauses":
            count = len(_split_contract(contract_text))
            return {"ok": True, "result": {"Ok": count}}
        else:
            return {"ok": False, "error": f"Unknown method: {method}"}

    def _llm_extract_clauses(self, contract_text: str) -> Dict[str, Any]:
        """Delegate clause extraction to the LLM-powered function."""
        from src.applets.clause_extractor import extract_clauses
        from src.types import ToolContext

        ctx = ToolContext(
            session_id="local-fallback",
            model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
            prompt_template_id="contract_clause_extract_v1",
        )
        clauses = extract_clauses(contract_text, ctx)
        result = [{"id": c.id, "title": c.title, "text": c.text} for c in clauses]
        logger.info("LLM clause extraction returned %d clauses", len(result))
        return {"ok": True, "result": {"Ok": result}}

    # ── Risk Scoring ─────────────────────────────────────────────────────

    def _handle_risk_scorer(self, method: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        if method == "score_clause_risk":
            clause_id = payload.get("clause_id", 0)
            clause_title = payload.get("clause_title", "")
            clause_text = payload.get("clause_text", "")
            if not clause_text.strip():
                return {"ok": False, "error": "clause_text cannot be empty"}

            # Try real LLM first
            if _llm_available():
                try:
                    return self._llm_score_clause(clause_id, clause_title, clause_text)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("LLM risk scoring failed (%s) — falling back to deterministic", exc)

            result = _score_single(clause_id, clause_title, clause_text)
            return {"ok": True, "result": {"Ok": result}}
        elif method == "score_all_clauses":
            contract_text = payload.get("contract_text", "")
            if not contract_text.strip():
                return {"ok": False, "error": "contract_text cannot be empty"}
            clauses = _split_contract(contract_text)
            results = [
                _score_single(c["id"], c["title"], c["text"]) for c in clauses
            ]
            return {"ok": True, "result": {"Ok": results}}
        else:
            return {"ok": False, "error": f"Unknown method: {method}"}

    def _llm_score_clause(self, clause_id: int, clause_title: str, clause_text: str) -> Dict[str, Any]:
        """Delegate risk scoring to the LLM-powered function."""
        from src.applets.risk_scorer import score_clause_risk
        from src.types import Clause, ToolContext

        ctx = ToolContext(
            session_id="local-fallback",
            model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
            prompt_template_id="contract_risk_score_v1",
        )
        clause = Clause(id=clause_id, title=clause_title, text=clause_text)
        risk = score_clause_risk(clause, ctx)
        result = {
            "clause_id": risk.clause_id,
            "clause_title": risk.clause_title,
            "risk_level": risk.risk_level.value,
            "confidence": str(risk.confidence),
            "reason": risk.reason,
            "flags": [{"code": f.split(":")[0].strip(), "description": f.split(":", 1)[-1].strip()} for f in risk.flags] if risk.flags else [],
        }
        logger.info("LLM risk score for clause %d: %s", clause_id, risk.risk_level.value)
        return {"ok": True, "result": {"Ok": result}}
