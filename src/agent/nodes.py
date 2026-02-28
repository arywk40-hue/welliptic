# src/agent/nodes.py
import os, time, hashlib, json
from anthropic import Anthropic
from pypdf import PdfReader
from src.agent.state import AgentState

client = Anthropic()

# ── Helpers ─────────────────────────────────────────────────

def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]

def _log(state: AgentState, event: str, data: dict) -> AgentState:
    """Local audit log — will be replaced with ctx.emit() at deploy time."""
    entry = {
        "step":      state["step_index"],
        "event":     event,
        "timestamp": int(time.time()),
        "data":      data
    }
    print(f"  📋 AUDIT [{event}] step={state['step_index']}")
    return {**state,
            "audit_log":  state["audit_log"] + [entry],
            "step_index": state["step_index"] + 1}

# ── Node 1: Ingest PDF ───────────────────────────────────────

def ingest_node(state: AgentState) -> AgentState:
    print("\n📄 [Node 1] Ingesting contract...")
    state = _log(state, "INGEST_START", {"filename": state["filename"]})

    # If text already provided (e.g. from Streamlit), skip PDF parse
    if state["contract_text"]:
        state = _log(state, "INGEST_DONE",
                     {"chars": len(state["contract_text"])})
        return state

    print("  ❌ No contract text found")
    return {**state, "fatal_error": True,
            "error_message": "No contract text provided"}

# ── Node 2: Extract Clauses ──────────────────────────────────

def extract_clauses_node(state: AgentState) -> AgentState:
    print("\n🔍 [Node 2] Extracting clauses...")
    state = _log(state, "LLM_INVOKE",
                 {"task": "clause_extraction",
                  "text_hash": _hash(state["contract_text"])})

    response = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=2048,
        messages=[{
            "role": "user",
            "content": f"""Extract all distinct clauses from this legal contract.
Return a JSON array where each item has:
- "id": clause number (1, 2, 3...)
- "title": short clause name
- "text": the full clause text

Contract:
{state["contract_text"][:6000]}

Return ONLY valid JSON, no explanation."""
        }]
    )

    try:
        raw = response.content[0].text.strip()
        # strip markdown fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        clauses = json.loads(raw.strip())
    except Exception as e:
        print(f"  ⚠️ Parse error: {e} — using fallback")
        clauses = [{"id": 1, "title": "Full Contract",
                    "text": state["contract_text"][:2000]}]

    state = _log(state, "CLAUSES_EXTRACTED", {"count": len(clauses)})
    print(f"  ✅ Found {len(clauses)} clauses")
    return {**state, "clauses": clauses, "current_clause_index": 0}

# ── Node 3: Score Risk ───────────────────────────────────────

def risk_score_node(state: AgentState) -> AgentState:
    idx = state["current_clause_index"]
    clause = state["clauses"][idx]
    print(f"\n⚖️  [Node 3] Scoring clause {idx+1}/{len(state['clauses'])}: {clause['title']}")

    state = _log(state, "LLM_INVOKE", {
        "task":        "risk_scoring",
        "clause_id":   clause["id"],
        "clause_hash": _hash(clause["text"])
    })

    response = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=512,
        messages=[{
            "role": "user",
            "content": f"""Analyse this legal clause for risk. Return JSON only:
{{
  "risk_level": "LOW" | "MEDIUM" | "HIGH",
  "confidence": 0.0-1.0,
  "reason": "one sentence explanation",
  "flags": ["list", "of", "specific", "concerns"]
}}

Clause: {clause['text'][:1500]}"""
        }]
    )

    try:
        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        result = json.loads(raw.strip())
    except Exception:
        result = {"risk_level": "UNKNOWN", "confidence": 0.0,
                  "reason": "Parse error", "flags": []}

    result["clause_id"]    = clause["id"]
    result["clause_title"] = clause["title"]

    state = _log(state, "RISK_SCORED", {
        "clause_id":  clause["id"],
        "risk_level": result["risk_level"],
        "confidence": result.get("confidence", 0)
    })

    print(f"  🎯 Risk: {result['risk_level']} "
          f"(confidence: {result.get('confidence', 0):.0%})")

    return {
        **state,
        "risk_results":        state["risk_results"] + [result],
        "current_clause_index": idx + 1
    }

# ── Node 4: Human Gate ───────────────────────────────────────

def human_gate_node(state: AgentState) -> AgentState:
    high_risk = [r for r in state["risk_results"]
                 if r["risk_level"] == "HIGH"]
    print(f"\n🚦 [Node 4] Human gate — {len(high_risk)} HIGH risk clauses found")

    state = _log(state, "HUMAN_GATE", {
        "high_risk_count": len(high_risk),
        "clauses":         [r["clause_title"] for r in high_risk]
    })

    # Print summary for human reviewer
    print("\n" + "="*50)
    print("⚠️  HUMAN REVIEW REQUIRED")
    print("="*50)
    for r in high_risk:
        print(f"  ❗ [{r['clause_title']}] — {r['reason']}")
    print("="*50)

    decision = input("\n  Approve contract? (approve/reject): ").strip().lower()
    if decision not in ["approve", "reject"]:
        decision = "reject"

    state = _log(state, "HUMAN_DECISION", {"decision": decision})
    return {**state,
            "human_gate_open": False,
            "human_decision":  decision}

# ── Node 5: Generate Report ──────────────────────────────────

def generate_report_node(state: AgentState) -> AgentState:
    print("\n📊 [Node 5] Generating final report...")
    state = _log(state, "REPORT_START", {
        "total_clauses": len(state["clauses"]),
        "decision":      state.get("human_decision", "auto")
    })

    high   = [r for r in state["risk_results"] if r["risk_level"] == "HIGH"]
    medium = [r for r in state["risk_results"] if r["risk_level"] == "MEDIUM"]
    low    = [r for r in state["risk_results"] if r["risk_level"] == "LOW"]

    report = f"""
╔══════════════════════════════════════════════╗
║         LEXAUDIT — CONTRACT RISK REPORT      ║
╚══════════════════════════════════════════════╝

File:      {state['filename']}
Decision:  {state.get('human_decision', 'AUTO-APPROVED').upper()}
Steps:     {state['step_index']} agent steps logged

RISK SUMMARY
─────────────────────────────────────────────
  🔴 HIGH:    {len(high)} clause(s)
  🟡 MEDIUM:  {len(medium)} clause(s)
  🟢 LOW:     {len(low)} clause(s)

HIGH RISK CLAUSES
─────────────────────────────────────────────
"""
    for r in high:
        report += f"  • {r['clause_title']}\n"
        report += f"    Reason: {r['reason']}\n"
        if r.get("flags"):
            report += f"    Flags:  {', '.join(r['flags'])}\n"
        report += "\n"

    report += f"""
AUDIT TRAIL
─────────────────────────────────────────────
  {len(state['audit_log'])} events logged
  Session: {state.get('session_id', 'local-dev (on-chain at deploy)')}
╔══════════════════════════════════════════════╗
║  NOTE: Audit trail will be on-chain after    ║
║  Weilchain deployment                        ║
╚══════════════════════════════════════════════╝
"""
    state = _log(state, "TERMINATE", {
        "reason":       "complete",
        "total_steps":  state["step_index"],
        "high_risk":    len(high)
    })
    print("  ✅ Report generated!")
    return {**state, "final_report": report}