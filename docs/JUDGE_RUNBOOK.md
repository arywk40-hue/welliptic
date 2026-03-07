# LexAudit — Judge Runbook

> Fastest path to verify all hackathon submission requirements in ~5 minutes.

---

## 0) Quick Start (TL;DR)

```bash
cd lexaudit
make check          # Verify env, imports, tests — all in one
make demo-offline   # Run offline analysis on sample contract (no API needed)
make serve          # Start API on :8000
# (new terminal)
make demo           # Run analysis on sample contract (uses Groq LLM)
```

---

## 1) Prerequisites

| Requirement | How to verify |
|---|---|
| Python 3.11+ | `python3 --version` |
| `.env` configured | `cat .env` (see `.env.example`) |
| `private_key.wc` exists | `ls private_key.wc` |
| Weilchain SDK installed | `python3 -c "from weil_ai import WeilAgent; print('OK')"` |

### LLM Provider (Priority Order)

LexAudit auto-selects the best available LLM:

| Priority | Provider | Env Vars | Model |
|---|---|---|---|
| 1 (fastest) | **Groq** ← recommended | `USE_GROQ=true` + `GROQ_API_KEY` | `llama-3.3-70b-versatile` |
| 2 | Gemini | `USE_GEMINI=true` + `GEMINI_API_KEY` | `gemini-2.0-flash` |
| 3 | OpenAI | `USE_OPENAI=true` + `OPENAI_API_KEY` | `gpt-4o` |
| 4 | Anthropic | `ANTHROPIC_API_KEY` | `claude-opus-4-1` |
| fallback | Deterministic | (none needed) | keyword heuristics |

## 2) Environment Check

```bash
make check
```

Expected output: all ✓ marks for env vars, WASM artifacts, Python imports, tests.

## 3) Run Tests

```bash
make test
```

Expected: **16/16 tests pass**:
- `test_clause_parser_handles_fenced_json` — WIDL clause validation
- `test_risk_parser_rejects_invalid_enum` — WIDL risk enum enforcement
- `test_cli_json_output` — End-to-end CLI with JSON output
- `test_happy_path_auto_approve` — Full pipeline, all LOW risk
- `test_human_gate_pending_when_high_risk` — Human gate triggers on HIGH
- `test_mcp_unavailable_fail_closed` — Fail-closed when MCP is down
- `test_parse_retry_then_fail` — Invalid applet output → retry → fail
- `test_clause_header_detection` — Header pattern matching
- `test_split_contract_numbered` — Numbered clause splitting
- `test_split_contract_fallback` — Plain text fallback (single clause)
- `test_risk_scoring_high` — HIGH keyword classification
- `test_risk_scoring_medium` — MEDIUM keyword classification
- `test_risk_scoring_low` — LOW (no indicators)
- `test_local_fallback_client_clause_extractor` — MCP client clause API
- `test_local_fallback_client_risk_scorer` — MCP client risk API
- `test_full_pipeline_with_local_fallback` — Full offline pipeline with human gate

## 4) Offline Demo (No API Keys Required)

```bash
make demo-offline
```

This runs the **full pipeline** using the `LocalFallbackMCPClient` — a deterministic client that mirrors the exact same logic as the on-chain Rust WASM applets (header-based clause splitting + keyword-based risk scoring). No LLM API key, no Weilchain node needed.

When an LLM is configured (Groq recommended), the LocalFallback **automatically delegates** to the AI-powered functions, producing genuine LLM-driven clause analysis and risk scoring.

Expected output:
- 9+ clauses extracted from sample NDA
- 9+ risk scores (with LLM: nuanced HIGH/MEDIUM/LOW; without: keyword-based)
- 35+ audit events (local JSONL)
- Result saved to `demo_output/demo_result.json`

A **pre-generated** demo result is also committed at `demo_output/demo_result.json` for instant review.

## 5) Start Server

```bash
make serve
# → http://localhost:8000
```

Verify:
```bash
curl http://localhost:8000/api/health | python3 -m json.tool
```

Expected:
```json
{
  "status": "ok",
  "llm": true,
  "llm_provider": "groq",
  "weilchain": true,
  "weil_middleware": true
}
```

## 6) Run CLI Analysis

```bash
python main.py --input contracts/sample_nda.txt --format json --no-human-gate
```

Expected:
- Clause extraction + risk scoring complete (powered by Groq LLM)
- Session ID printed
- Audit events logged to `.runs/`

## 7) API Analysis

```bash
curl -X POST http://localhost:8000/api/analyse \
  -H "Content-Type: application/json" \
  -d '{"contract_text": "1. INDEMNIFICATION: Party shall indemnify...", "no_human_gate": true}' \
  | python3 -m json.tool
```

## 8) Next.js UI

```bash
cd ui && npm run dev
# → http://localhost:3000
```

- Upload a contract → watch real-time agent feed
- See risk distribution chart
- View audit trail with Weilchain transaction links

## 9) Verify On-Chain Audit Trail

Check latest run:
```bash
ls -1t .runs/*.jsonl | head -1 | xargs head -5
```

Each event has:
- `weilchain_tx_status`, `weilchain_batch_id`, `weilchain_block_height`

## 10) WASM Applet Verification

Pre-compiled WASM artifacts:
```bash
ls -la src/applets/wasm/
```

Deployed applet IDs in `.env`:
```bash
grep APPLET_ID .env
```

Both deployed and **Finalized** on Weilchain (block ~3879551).

## 11) Hackathon Requirement Mapping

| Requirement | Where | Lines |
|---|---|---|
| **Agentic framework** (LangGraph-compatible) | `src/agent/control_loop.py` | 632 |
| **Custom control loop** | `src/agent/control_loop.py` | 632 |
| **Multi-LLM support** (Groq/Gemini/OpenAI/Anthropic) | `src/applets/clause_extractor.py`, `risk_scorer.py` | — |
| **LLM-enhanced fallback** | `src/tools/local_fallback.py` | 300+ |
| **Weilchain audit logging** | `src/agent/audit.py` | 262 |
| **MCP applet execution** | `src/tools/router.py` | 520 |
| **Auto-fallback (offline + online)** | `src/tools/router.py`, `local_fallback.py` | — |
| **WIDL interfaces** | `src/applets/*.widl` | 53 |
| **Rust WASM applets** | `rust_applets/*/src/lib.rs` | 284 |
| **weil_ai SDK** (WeilAgent, middleware, auth) | `src/agent/audit.py`, `src/api/server.py` | — |
| **weil_wallet SDK** (WeilClient, contracts) | `src/tools/router.py` | — |
| **Human-in-the-loop gate** | `src/agent/control_loop.py:_node_human_gate` | ~30 |
| **Fail-closed behavior** | `src/tools/router.py`, tests | — |
| **Dual audit trail** (local JSONL + on-chain) | `src/agent/audit.py` | 262 |
| **Cryptographic auth** (wallet signatures) | `src/agent/audit.py:get_auth_headers()` | — |
| **Next.js UI** (Upload → Analysis → Review → Report) | `ui/` | 5 screens |
| **FastAPI server** | `src/api/server.py` | 210 |
