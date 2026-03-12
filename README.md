# LexAudit — AI Legal Contract Review with On-Chain Audit Trail

> **Weilliptic Hackathon 2026** — Problem Statement: *"Use an external agentic framework (LangChain / Google ADK) and add Weilliptic audit logging into the mix."*

LexAudit is an AI-powered legal contract review agent that extracts clauses, scores risks, enforces a human-in-the-loop gate, and records **every step as an immutable on-chain audit trail** on Weilchain — with **100% on-chain delivery** for all audit events.

Quick verification guide: [docs/JUDGE_RUNBOOK.md](docs/JUDGE_RUNBOOK.md)

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                        LexAudit Agent                            │
│                                                                  │
│  ┌──────────┐   ┌──────────────┐   ┌───────────┐   ┌─────────┐ │
│  │  INGEST   │──▶│ EXTRACT_CLAUSES│──▶│ RISK_SCORE│──▶│ HUMAN   │ │
│  │           │   │  (MCP Applet)  │   │(MCP Applet)│  │  GATE   │ │
│  └──────────┘   └──────────────┘   └───────────┘   └────┬────┘ │
│                                                          │      │
│                                                    ┌─────▼────┐ │
│                                                    │ TERMINATE │ │
│                                                    │ + REPORT  │ │
│                                                    └──────────┘ │
│                                                                  │
│  Every node emits ──▶  WeilAuditLogger  ──▶  Weilchain (on-chain)│
│                        (weil_ai.WeilAgent)                       │
└──────────────────────────────────────────────────────────────────┘
         │                                            │
    ┌────▼────┐                                 ┌─────▼─────┐
    │ FastAPI  │◀── Next.js UI (port 3000) ────▶│ Weilchain  │
    │ :8000    │    weil_middleware() auth       │   Node     │
    └─────────┘                                 └───────────┘
```

### Pipeline

| Step | Node | What Happens |
|------|------|-------------|
| 1 | **INIT** | Session created, contract ingested, SHA-256 hash recorded |
| 2 | **INGEST** | Contract text normalized, character count + preview logged |
| 3 | **EXTRACT_CLAUSES** | MCP call to `ClauseExtractor` applet → returns structured clauses |
| 4 | **RISK_SCORE** (loop) | For each clause: MCP call to `RiskScorer` applet → LOW/MEDIUM/HIGH |
| 5 | **HUMAN_GATE** | If any clause ≥ threshold → pipeline **pauses**, human must approve/reject (on-chain) |
| 6 | **TERMINATE** | Final report generated, audit summary persisted |

Every step emits a dual audit event (100% delivery rate):
- **Local**: Append to `.runs/<session>.jsonl` (JSONL with input/output hashes)
- **On-chain**: Submit via `WeilAgent.audit()` → Weilchain transaction with `batch_id` + `block_height`

> **On-chain delivery**: A persistent event loop keeps the httpx connection pool alive across calls, achieving 100% transaction delivery (vs ~60% with the SDK's default `asyncio.run()` pattern on Python 3.13).

---

## Weilliptic SDK Integration

LexAudit uses **every major surface** of the Weilchain ADK:

### `weil_ai.WeilAgent` — Agent Identity Proxy

The control loop wraps a lightweight agent sentinel with `WeilAgent`, which provides:

```python
from weil_ai import WeilAgent

agent = WeilAgent(sentinel, private_key_path="private_key.wc")
agent.audit(json_log)          # on-chain audit log
agent.get_auth_headers()       # signed MCP headers
agent.weil_wallet              # underlying Wallet
```

Every audit event (29+ per contract analysis) is submitted on-chain via `WeilAgent.audit()`.

### `weil_ai.weil_middleware()` — Cryptographic Request Auth

Both FastAPI servers add `weil_middleware()` which verifies:

- `X-Wallet-Address` — hex-encoded wallet address
- `X-Signature` — secp256k1 compact signature
- `X-Message` — canonical JSON payload
- `X-Timestamp` — replay protection (5-minute window)

```python
from weil_ai import weil_middleware

app.add_middleware(weil_middleware())
```

### `weil_ai.build_auth_headers()` — Signed MCP Headers

The HTTP MCP client injects signed headers into every applet invocation:

```python
headers = weil_audit.get_auth_headers()  # from WeilAgent
router = ToolRouter(settings, weil_auth_headers=headers)
# → every MCP POST includes X-Wallet-Address, X-Signature, etc.
```

### `weil_wallet.WeilClient` — Low-Level Chain Access

Used internally by `WeilAgent` for transaction submission:

- `WeilClient.audit(log)` → `TransactionResult` with `.status`, `.block_height`, `.batch_id`
- `WeilClient.execute(contract_id, method, args)` → direct applet invocation
- `WeilClient.get_applet_id_for_name()` → applet discovery

### WIDL Interfaces (`@mcp` annotated)

Two applets defined with Weilchain Interface Definition Language:

**`ClauseExtractor`** (`clause_extractor.widl`):
```widl
@mcp
interface ClauseExtractor {
    query func extract_clauses(contract_text: string) -> result<list<Clause>, string>;
}
```

**`RiskScorer`** (`risk_scorer.widl`):
```widl
@mcp
interface RiskScorer {
    query func score_clause_risk(clause_id: u32, clause_title: string, clause_text: string) -> result<RiskScore, string>;
}
```

### Rust WASM Applets

Both applets have production Rust implementations in `rust_applets/` that compile to `wasm32-unknown-unknown` for on-chain execution:

- `clause_extractor/src/lib.rs` — structural clause parsing (header detection, section splitting)
- `risk_scorer/src/lib.rs` — keyword-based risk classification with configurable flag codes

Build: `cd rust_applets && ./build.sh`

---

## On-Chain Integration

### Audit Flow

```
Agent Step → WeilAuditLogger.emit()
               ↓
         WeilAgent.audit(json_log)
               ↓
         WeilClient._audit_async(log)
               ↓
         POST /v1/audit → Weilchain Sentinel
               ↓
         TransactionResult {
           status: IN_PROGRESS → CONFIRMED → FINALIZED,
           block_height: 12345,
           batch_id: "abc123..."
         }
```

Each local audit event is enriched with the on-chain tx metadata:

```json
{
  "step_index": 5,
  "event_type": "RISK_SCORED",
  "node": "risk_score",
  "metadata": {
    "clause_id": 2,
    "risk_level": "HIGH",
    "weilchain_tx_status": "TransactionStatus.IN_PROGRESS",
    "weilchain_batch_id": "a1b2c3...",
    "weilchain_block_height": 42
  }
}
```

### Applet Deployment

```bash
# Build WASM applets
cd rust_applets && ./build.sh

# Deploy to Weilchain pod
./scripts/deploy.sh
# → outputs CLAUSE_EXTRACTOR_APPLET_ID and RISK_SCORER_APPLET_ID
```

### MCP Tool Router

The `ToolRouter` dispatches to deployed Weilchain applets through the Python SDK (`WeilClient.execute`) and normalizes SDK envelopes (`Ok`/`Err`/`result`) before schema validation.

Retry logic with exponential backoff remains bounded and fail-closed.

---

## Innovation

### 1. Dual Audit Trail (Local + On-Chain) — 100% Delivery

Every agent step produces both a local JSONL record (for debugging/replay) and an on-chain Weilchain transaction (for tamper-proof compliance). The local event is enriched with the chain tx metadata, creating a **cross-referenced audit trail**.

A persistent background event loop keeps the Weilchain httpx connection pool alive, achieving **100% on-chain delivery** (the SDK's default `asyncio.run()` pattern drops ~40% of transactions on Python 3.13 due to a TLS socket close race).

### 2. Deterministic Control Loop

The production pipeline uses a deterministic control loop (`control_loop.py`, 668 lines) that guarantees:
- Step budget enforcement (max_steps)
- Parse retry with structured validation against WIDL schemas
- Fail-closed on MCP unavailability
- Human gate with configurable risk threshold (enabled by default — HIGH-risk contracts **require** human approval)

### 3. Human-in-the-Loop Gate

When any clause scores ≥ the configured threshold (default: HIGH), the pipeline **pauses** and returns `pending_human_review: true`. The UI shows flagged clauses with Approve/Reject buttons. The human decision is recorded on-chain via `/api/continue`. Contracts with only LOW/MEDIUM risk are auto-approved.

### 4. Local Fallback MCP Client

When the Weilchain SDK or Sentinel node is unreachable, the `LocalFallbackMCPClient` (`src/tools/local_fallback.py`) mirrors the **exact same logic** as the Rust WASM applets deployed on-chain — header-based clause splitting and keyword-based risk classification. This is **not a mock**: it produces identical output to the on-chain applets and allows the full pipeline to run offline for demos and testing.

### 5. WIDL-to-Validation Pipeline

Applet interfaces are defined in WIDL. The Python parsers (`clause_extractor.py`, `risk_scorer.py`) validate every MCP response against the WIDL schema types (e.g., `result<list<Clause>, string>`, `result<RiskScore, string>`) with strict type checking. Invalid responses trigger parse retries.

### 6. Cryptographic End-to-End Auth

The full request chain is cryptographically signed:
- UI → FastAPI: `weil_middleware()` verifies wallet signature
- FastAPI → MCP Applets: `get_auth_headers()` signs every invocation
- MCP Applets → Weilchain: applet execution produces chain transactions

### 7. Weilchain-Secured MCP Server (FastMCP)

`src/mcp_server.py` hosts ClauseExtractor and RiskScorer as proper MCP tools using **FastMCP** with the canonical Weilchain pattern:

```python
from fastmcp import FastMCP
from weil_ai.mcp import secured, weil_middleware

mcp = FastMCP("lexaudit-mcp")

@mcp.tool()
@secured("lexaudit::clause_extractor")  # on-chain access control
async def extract_clauses(contract_text: str) -> str: ...

app = mcp.http_app(transport="streamable-http")
app.add_middleware(weil_middleware())    # wallet-signature verification
```

This is the same pattern from `wadk-sdk/adk/python/examples/mcp_server.py` — `@secured()` checks `key_has_purpose` on-chain, and `weil_middleware()` verifies wallet signatures on every POST.

Start with: `python main.py --serve-mcp` (port 8001).

---

## User Experience

### Next.js UI (port 3000)

Modern dark-themed interface with:
- Drag-and-drop contract upload (.txt, .pdf, .doc, .docx)
- Live agent feed showing each pipeline step in real-time
- Risk distribution chart (Recharts)
- Clause-by-clause risk breakdown with flags
- Full audit trail with Weilchain transaction links
- Human gate review screen

### Neural Console (port 8000, `/web`)

Single-page React app served by FastAPI with:
- Contract text input + risk threshold selector
- Live event feed with status indicators
- Bar chart risk distribution
- Expandable audit trail with tx hashes and Weilchain links

### CLI

```bash
python main.py --input contract.txt --format json --no-human-gate
python main.py --input contract.txt --human-gate-threshold MEDIUM
python main.py --serve       # Start FastAPI on port 8000
python main.py --serve-mcp   # Start Weilchain-secured MCP server on port 8001
cat contract.txt | python main.py --input -  # Pipe from stdin
```

---

## Setup

### Prerequisites

- Python 3.11+
- Rust toolchain with `wasm32-unknown-unknown` target
- Node.js 18+ (for Next.js UI)

### Install

```bash
cd lexaudit

# Python dependencies
pip install -r requirements.txt

# Weilchain SDK (from WADK repo)
git clone https://github.com/weilliptic-public/wadk.git ../wadk-sdk
pip install ../wadk-sdk/adk/python/weil_wallet
pip install ../wadk-sdk/adk/python/weil_ai

# Generate Weilchain wallet
python3 -c "import os; open('private_key.wc','w').write(os.urandom(32).hex())"

# Build Rust WASM applets
cd rust_applets && ./build.sh && cd ..

# Next.js UI
cd ui && npm install && cd ..
```

### Configure

Copy `.env.example` to `.env` and fill in:

```bash
ANTHROPIC_API_KEY=sk-ant-...
WEILCHAIN_WALLET_PATH=./private_key.wc
WEILCHAIN_NODE_URL=https://your-weilchain-node
CLAUSE_EXTRACTOR_APPLET_ID=applet_...
RISK_SCORER_APPLET_ID=applet_...
```

### Run

```bash
# FastAPI server
python main.py --serve

# Next.js UI (separate terminal)
cd ui && npm run dev

# CLI analysis
python main.py --input my_contract.txt --format json --no-human-gate
```

### Test

```bash
python -m pytest tests/ -v
```

All 23 tests pass:
- `test_clause_parser_handles_fenced_json` — WIDL clause validation
- `test_risk_parser_rejects_invalid_enum` — WIDL risk enum enforcement
- `test_risk_parser_accepts_all_valid_levels` — All risk levels accepted
- `test_clause_parser_handles_empty_contract` — Empty input handling
- `test_cli_json_output` — End-to-end CLI with JSON output
- `test_cli_with_sample_high_risk_contract` — High-risk contract CLI test
- `test_happy_path_auto_approve` — Full pipeline, all LOW risk
- `test_human_gate_pending_when_high_risk` — Human gate triggers on HIGH
- `test_mcp_unavailable_fail_closed` — Fail-closed when MCP is down
- `test_parse_retry_then_fail` — Invalid applet output → retry → fail
- `test_step_budget_termination` — Max steps budget enforcement
- `test_audit_events_emitted_at_every_node` — Every node emits audit events
- `test_human_gate_reject_path` — Human reviewer rejects contract
- `test_clause_header_detection` — Header pattern matching
- `test_split_contract_numbered` — Numbered clause splitting
- `test_split_contract_fallback` — Plain text fallback (single clause)
- `test_risk_scoring_high` — HIGH keyword classification
- `test_risk_scoring_medium` — MEDIUM keyword classification
- `test_risk_scoring_low` — LOW (no indicators)
- `test_local_fallback_client_clause_extractor` — MCP client clause API
- `test_local_fallback_client_risk_scorer` — MCP client risk API
- `test_full_pipeline_with_local_fallback` — Full offline pipeline (4 clauses, human gate)
- `test_groq_llm_delegation_risk_scoring` — Groq LLM delegation for risk scoring

---

## Project Structure

```
welliptic/                               # ← GitHub repo root
├── main.py                              # CLI entry point
├── server.py                            # FastAPI server entry point
├── Makefile                             # Build / test / deploy commands
├── Dockerfile                           # Multi-stage Docker build
├── docker-compose.yml                   # API + UI orchestration
├── requirements.txt                     # Python dependencies
├── package.json                         # JS SDK (deploy scripts)
├── contracts/                           # Sample contracts for demo
│   └── sample_nda.txt
├── src/
│   ├── config.py                        # Settings from env vars
│   ├── types.py                         # Clause, RiskScore, AgentState, AuditEvent
│   ├── agent/
│   │   ├── control_loop.py              # Deterministic pipeline (668 lines)
│   │   ├── audit.py                     # AuditLogger + WeilAuditLogger (100% on-chain delivery)
│   │   └── adk_workflow.py              # ADK-oriented entry point
│   ├── tools/
│   │   ├── router.py                    # ToolRouter → WeilchainHTTPMCPClient
│   │   └── local_fallback.py            # Deterministic offline MCP client
│   ├── applets/
│   │   ├── clause_extractor.py          # WIDL validation + LLM extraction
│   │   ├── clause_extractor.widl        # @mcp ClauseExtractor interface
│   │   ├── risk_scorer.py               # WIDL validation + LLM scoring
│   │   ├── risk_scorer.widl             # @mcp RiskScorer interface
│   │   └── wasm/                        # Pre-compiled WASM binaries
│   ├── mcp_server.py                    # FastMCP + @secured + weil_middleware (port 8001)
│   └── api/
│       └── server.py                    # FastAPI routes + middleware
├── rust_applets/                        # Rust source for on-chain applets
│   ├── build.sh
│   ├── clause_extractor/src/lib.rs
│   └── risk_scorer/src/lib.rs
├── ui/                                  # Next.js frontend
│   ├── app/                             # Pages (upload → analysis → report)
│   ├── components/                      # React components
│   ├── lib/                             # API client + state store
│   └── package.json
├── tests/                               # 23 tests (all passing)
│   ├── conftest.py                      # Shared fixtures + InMemoryMCPClient
│   ├── test_applets_parsing.py
│   ├── test_cli.py
│   ├── test_control_loop.py
│   └── test_local_fallback.py           # 10 tests for offline fallback client
├── demo_output/                         # Pre-generated demo results
│   └── demo_result.json                 # 9-clause NDA analysis (offline)
├── scripts/
│   ├── deploy.sh                        # Full deploy pipeline
│   ├── deploy_applets.mjs               # JS SDK applet deployment
│   ├── verify_deploy.sh                 # Post-deploy verification
│   └── verify_real_mcp.py               # E2E MCP verification
├── docs/
│   ├── ARCHITECTURE.md                  # Detailed architecture
│   └── JUDGE_RUNBOOK.md                 # Quick verification guide
└── web/
    └── index.html                       # Backup SPA (served at :8000)
```

---

## License

Built for the Weilliptic Hackathon 2026.
