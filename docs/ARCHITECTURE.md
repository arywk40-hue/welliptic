# LexAudit — Architecture Overview

## System Architecture

```
                    ┌─────────────────────────────────┐
                    │         User Interfaces          │
                    │                                  │
                    │  ┌──────────┐   ┌─────────────┐ │
                    │  │ Next.js  │   │  CLI (main.py)│ │
                    │  │ :3000    │   │              │ │
                    │  └────┬─────┘   └──────┬──────┘ │
                    └───────┼────────────────┼────────┘
                            │                │
                    ┌───────▼────────────────▼────────┐
                    │       FastAPI  :8000             │
                    │  ┌────────────────────────────┐  │
                    │  │   CORS + weil_middleware()  │  │
                    │  │  (wallet signature verify)  │  │
                    │  └─────────────┬──────────────┘  │
                    │                │                  │
                    │  ┌─────────────▼──────────────┐  │
                    │  │   Agentic Control Loop      │  │
                    │  │   (control_loop.py)          │  │
                    │  │                              │  │
                    │  │  INIT → INGEST → EXTRACT     │  │
                    │  │    → RISK_SCORE → HUMAN_GATE │  │
                    │  │    → TERMINATE + REPORT       │  │
                    │  └───────┬──────────┬──────────┘  │
                    │          │          │              │
                    │  ┌───────▼──┐  ┌───▼──────────┐  │
                    │  │ ToolRouter│  │WeilAuditLogger│ │
                    │  │(router.py)│  │  (audit.py)  │  │
                    │  └───────┬──┘  └───┬──────────┘  │
                    └──────────┼─────────┼─────────────┘
                               │         │
                    ┌──────────▼─────────▼─────────────┐
                    │         Weilchain Network         │
                    │                                   │
                    │  ┌──────────┐  ┌───────────────┐  │
                    │  │ Clause   │  │  Audit Ledger  │  │
                    │  │ Extractor│  │  (immutable)   │  │
                    │  │ (WASM)   │  │                │  │
                    │  └──────────┘  └───────────────┘  │
                    │  ┌──────────┐                     │
                    │  │ Risk     │                     │
                    │  │ Scorer   │                     │
                    │  │ (WASM)   │                     │
                    │  └──────────┘                     │
                    │                                   │
                    │  Sentinel: sentinel.weilliptic.ai  │
                    │  POD:      marauder.weilliptic.ai  │
                    └───────────────────────────────────┘
```

## Module Dependency Graph

```
main.py ──────────────┐
server.py ────────┐   │
                  ▼   ▼
           src/api/server.py
                  │
                  ▼
        src/agent/control_loop.py  ◀── src/agent/adk_workflow.py
           │         │        │
           ▼         ▼        ▼
   src/tools/   src/agent/   src/applets/
   router.py    audit.py     clause_extractor.py
                             risk_scorer.py
           │         │        │
           ▼         ▼        ▼
      weil_wallet  weil_ai   *.widl (schema)
      (SDK)        (SDK)
```

## Data Flow

```
Contract Text
    │
    ▼
┌─ INGEST ──────────────────────────────────┐
│  Normalize → SHA-256 hash → audit log     │
└──────────────────────────────┬────────────┘
                               │
    ▼
┌─ EXTRACT_CLAUSES ─────────────────────────┐
│  MCP → ClauseExtractor applet (on-chain)  │
│  → Parse response against WIDL schema     │
│  → Validate: list<Clause>                 │
│  → Retry on parse failure (max 2)         │
└──────────────────────────────┬────────────┘
                               │
    ▼
┌─ RISK_SCORE (loop per clause) ────────────┐
│  MCP → RiskScorer applet (on-chain)       │
│  → Parse: RiskScore {level, flags}        │
│  → Classify: LOW / MEDIUM / HIGH          │
└──────────────────────────────┬────────────┘
                               │
    ▼
┌─ HUMAN_GATE ──────────────────────────────┐
│  If any risk ≥ threshold → require review │
│  Decision: approve / reject / auto-approve│
└──────────────────────────────┬────────────┘
                               │
    ▼
┌─ TERMINATE ───────────────────────────────┐
│  Generate final report                    │
│  Persist audit summary                    │
│  Return AuditResult to caller             │
└───────────────────────────────────────────┘
```

## Key Design Decisions

1. **Deterministic Control Loop** — No LLM in the hot path for control flow. Claude is used for clause extraction prompts; the loop itself is a state machine with explicit transitions.

2. **Dual Audit Trail** — Every step logs both locally (`.runs/session.jsonl`) and on-chain (`WeilAgent.audit()`). Local events are enriched with chain tx metadata.

3. **Fail-Closed** — If MCP applets are unreachable, the pipeline halts with an error rather than producing unaudited results.

4. **WIDL Schema Validation** — Every MCP response is validated against the WIDL type definitions before being accepted. Parse failures trigger retries.

5. **Cryptographic Auth Chain** — UI → API (weil_middleware) → MCP (build_auth_headers) → Chain (wallet signature). Every hop is authenticated.
