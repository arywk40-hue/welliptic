# LexAudit — Architecture

## Overview

LexAudit is an agentic contract risk analysis application that uses a deterministic control loop to extract clauses from legal contracts, score each clause for risk, and produce a structured audit trail. Every step of the analysis is logged both locally (JSONL file) and optionally on-chain via the Weilchain ADK, providing a tamper-evident audit record.

**Key capabilities:**
- Automatic clause extraction from contract text using MCP-based WASM applets
- Per-clause risk scoring (LOW / MEDIUM / HIGH) with confidence scores and flags
- Human review gate for contracts with high-risk clauses
- Dual-layer audit logging: local JSONL + Weilchain on-chain transactions
- CLI and REST API interfaces

---

## Architecture Diagram

```
CLI / FastAPI
     │
     ▼
AuditLogger (local JSONL)
     │
     ├──► WeilAuditLogger (on-chain via WeilAgent)
     │
     ▼
Control Loop (control_loop.py)
     │
     ▼
ToolRouter (router.py)
     │
     ├──► WeilchainSDKMCPClient  ──► MCP Applets (WASM on Weilchain)
     │         │                          ├── ClauseExtractor
     │         │                          └── RiskScorer
     └──► LocalFallbackMCPClient (if Weilchain unavailable)
```

Full system view:

```
CLI / FastAPI → AuditLogger + WeilAuditLogger → ToolRouter → MCP Applets (WASM on Weilchain)
```

---

## Component Table

| File | Role |
|------|------|
| `main.py` | CLI entry point; parses arguments and calls `run_lexaudit` |
| `src/api/server.py` | FastAPI server with CORS and `weil_middleware()` for wallet auth |
| `src/agent/control_loop.py` | Deterministic agentic control loop (state machine) |
| `src/agent/audit.py` | `AuditLogger` (local JSONL) and `WeilAuditLogger` (on-chain) |
| `src/agent/adk_workflow.py` | ADK workflow integration helpers |
| `src/config.py` | Pydantic `Settings` loaded from environment variables |
| `src/tools/router.py` | `ToolRouter` — dispatches MCP calls with retry logic |
| `src/tools/local_fallback.py` | `LocalFallbackMCPClient` — pure-Python fallback when Weilchain is unavailable |
| `src/applets/clause_extractor.py` | Python parser for ClauseExtractor MCP responses |
| `src/applets/risk_scorer.py` | Python parser for RiskScorer MCP responses |
| `src/applets/clause_extractor.widl` | WIDL interface definition for the ClauseExtractor applet |
| `src/applets/risk_scorer.widl` | WIDL interface definition for the RiskScorer applet |
| `src/types.py` | Shared dataclasses: `Clause`, `RiskScore`, `AuditEvent`, `AuditResult`, `AgentState` |

---

## Agentic Loop

The `run_lexaudit` function in `control_loop.py` implements a step-limited state machine. Each transition emits an audit event. The sequence for a typical run is:

1. **INIT** — Initialize `AgentState`, emit `INIT` audit event with filename and `max_steps`.
2. **INGEST_START / INGEST_DONE** — Read and normalize contract text; hash the input for the audit log.
3. **TOOL_PREDICT** (`clause_extractor`) — Select the extraction method; log predicted call with `prompt_template_id`.
4. **TOOL_EXECUTE** (`clause_extractor`) — Call `extract_clauses` via MCP; parse the `Vec<Clause>` response.
5. **CLAUSES_EXTRACTED** — Store clauses in state; emit event with clause count.
6. *For each clause (repeated):*
   - **TOOL_PREDICT** (`risk_scorer`) — Select `score_clause_risk`; log with `clause_id`.
   - **TOOL_EXECUTE** (`risk_scorer`) — Call MCP; parse `RiskScore` response.
   - **RISK_SCORED** — Store result; emit event with risk level.
7. **HUMAN_GATE** — If any clause exceeds the risk threshold and a `decision_provider` is present, request a human decision. If no provider, set `pending_human_review = True` and terminate early.
8. **HUMAN_DECISION** — Log the decision (`approve`, `reject`, or `auto-approved`).
9. **TERMINATE** — Generate the final report; persist the audit summary; return `AuditResult`.

---

## Audit Logging Architecture

LexAudit uses a **dual-layer** audit strategy:

### Layer 1 — Local JSONL (`AuditLogger`)

Every call to `AuditLogger.emit()` writes a JSON line to `.runs/<session_id>.jsonl`. Fields recorded per event:

| Field | Description |
|-------|-------------|
| `step_index` | Monotonically incrementing counter |
| `event_type` | String identifier (e.g. `INIT`, `TOOL_EXECUTE`) |
| `timestamp` | Unix epoch seconds |
| `node` | Pipeline node name |
| `input_hash` | SHA-256 (first 16 hex chars) of input payload |
| `output_hash` | SHA-256 (first 16 hex chars) of output payload |
| `latency_ms` | Tool call duration in milliseconds |
| `model` | LLM model used (if any) |
| `tool_name` | MCP applet name (if any) |
| `status` | `ok` or `error` |
| `error` | Error message if status is `error` |
| `metadata` | Arbitrary key-value context |

At the end of a run, `AuditLogger.summary()` writes a `audit_summary.json` file with aggregate statistics.

### Layer 2 — On-chain (`WeilAuditLogger`)

`WeilAuditLogger` wraps `weil_ai.WeilAgent` with a lightweight sentinel identity. Each `emit()` call serializes the event to JSON and submits it via `WeilAgent.audit(log_entry)`, which posts a transaction to the Weilchain ledger. Transaction results (status, block height, batch ID, tx hash) are stored in `tx_results`.

`WeilAuditLogger` fails open: if the SDK is missing, the wallet file does not exist, or the chain is unreachable, it silently disables itself and all local JSONL logging continues unaffected.

---

## Weilchain SDK Integration

The Weilchain ADK provides three key components:

| SDK Symbol | Usage |
|------------|-------|
| `weil_wallet.PrivateKey` | Load wallet identity from `.wc` file |
| `weil_wallet.Wallet` | Sign messages and transactions |
| `weil_ai.WeilAgent` | Proxy agent for on-chain audit and MCP auth |
| `weil_middleware()` | FastAPI middleware for wallet signature verification |

Authentication flow:
1. `WeilAuditLogger._initialize()` loads the private key from `WEILCHAIN_WALLET_PATH`.
2. `WeilAgent` is constructed with the wallet identity.
3. `WeilAgent.get_auth_headers()` produces signed HTTP headers (`X-Wallet-Address`, `X-Signature`, `X-Message`, `X-Timestamp`).
4. `ToolRouter` passes these headers to the MCP client for every applet call.
5. The Weilchain MCP server verifies headers via `weil_middleware()`.

---

## Tool Execution

MCP applet calls follow this flow:

```
ToolRouter.call_tool()
    │
    ├── Build payload from AgentState
    ├── Emit TOOL_PREDICT audit event
    ├── Call MCP client (WeilchainSDKMCPClient or LocalFallbackMCPClient)
    │       │
    │       └── Returns: { ok: bool, result: { Ok: T } | { Err: string } }
    ├── Parse response with applet-specific parser (_extract_payload)
    ├── Validate parsed result against expected type
    ├── Emit TOOL_EXECUTE audit event (with latency_ms)
    └── Return ToolResult
```

On parse failure, `ToolRouter` retries up to `LEXAUDIT_MAX_RETRIES` times with exponential backoff (`LEXAUDIT_RETRY_BACKOFF`). If all retries fail, the pipeline terminates with `fatal_error = True` and `terminate_reason = "INVALID_TOOL_OUTPUT"`.

If `LEXAUDIT_ENFORCE_MCP=true` and the MCP client reports `is_available() = False`, the pipeline raises `McpUnavailableError` immediately (fail-closed).

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | _(required)_ | Anthropic API key for Claude |
| `ANTHROPIC_MODEL` | `claude-opus-4-1` | Claude model identifier |
| `LEXAUDIT_MAX_RETRIES` | `2` | Max retries for failed MCP calls |
| `LEXAUDIT_RETRY_BACKOFF` | `0.3` | Backoff multiplier in seconds |
| `LEXAUDIT_RUNS_DIR` | `.runs` | Directory for local JSONL audit logs |
| `LEXAUDIT_ENFORCE_MCP` | `true` | Fail if MCP is unavailable |
| `WEILCHAIN_WALLET_PATH` | `./private_key.wc` | Path to Weilchain wallet file |
| `WEILCHAIN_NODE_URL` | `https://sentinel.unweil.me` | Weilchain node endpoint |
| `WEILCHAIN_MCP_TIMEOUT` | `20.0` | MCP call timeout in seconds |
| `CLAUSE_EXTRACTOR_APPLET_ID` | _(set after deploy)_ | Deployed ClauseExtractor applet ID |
| `RISK_SCORER_APPLET_ID` | _(set after deploy)_ | Deployed RiskScorer applet ID |

---

## Human Gate

The human gate is triggered when at least one clause scores `HIGH` risk. Behavior depends on whether a `decision_provider` callable is supplied:

- **With `decision_provider`**: The callable receives the list of `RiskScore` objects and returns a decision string (`"approve"`, `"reject"`, or `"auto-approved"`). The gate logs a `HUMAN_DECISION` event with the result.
- **Without `decision_provider`** (default in CLI with `--no-human-gate`): `pending_human_review` is set to `True`, the run terminates with `terminate_reason = "HUMAN_REVIEW_PENDING"`, and the caller is expected to re-run with a decision.

The gate threshold is configurable and defaults to any `HIGH`-risk clause requiring review.

---

## Running Locally

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure environment
cp .env.example .env
# Edit .env with your ANTHROPIC_API_KEY and optional Weilchain settings

# 3. Run CLI (local fallback mode — no Weilchain required)
python main.py --input contract.txt --format json --no-human-gate

# 4. Start REST API server
python server.py
# or
uvicorn src.api.server:app --reload

# 5. Run tests
pytest tests/

# 6. Deploy WASM applets to Weilchain (optional)
make deploy
```
