# LexAudit — Judge Runbook

> Fastest path to verify all hackathon submission requirements in ~5 minutes.

---

## 0) Quick Start (TL;DR)

```bash
cd lexaudit
make check          # Verify env, imports, tests — all in one
make serve          # Start API on :8000
# (new terminal)
make demo           # Run analysis on sample contract
```

---

## 1) Prerequisites

| Requirement | How to verify |
|---|---|
| Python 3.11+ | `python3 --version` |
| `.env` configured | `cat .env` (see `.env.example`) |
| `private_key.wc` exists | `ls private_key.wc` |
| Weilchain SDK installed | `python3 -c "from weil_ai import WeilAgent; print('OK')"` |

## 2) Environment Check

```bash
make check
```

Expected output: all ✓ marks for env vars, WASM artifacts, Python imports, tests.

## 3) Run Tests

```bash
make test
```

Expected: **7/7 tests pass**:
- `test_clause_parser_handles_fenced_json` — WIDL clause validation
- `test_risk_parser_rejects_invalid_enum` — WIDL risk enum enforcement
- `test_cli_json_output` — End-to-end CLI with JSON output
- `test_happy_path_auto_approve` — Full pipeline, all LOW risk
- `test_human_gate_pending_when_high_risk` — Human gate triggers on HIGH
- `test_mcp_unavailable_fail_closed` — Fail-closed when MCP is down
- `test_parse_retry_then_fail` — Invalid applet output → retry → fail

## 4) Start Server

```bash
make serve
# → http://localhost:8000
```

Verify:
```bash
curl http://localhost:8000/api/health | python3 -m json.tool
```

Expected: `{"status": "ok", "claude": true, "weilchain": true}`

## 5) Run CLI Analysis

```bash
python main.py --input contracts/sample_nda.txt --format json --no-human-gate
```

Expected:
- Clause extraction + risk scoring complete
- Session ID printed
- Audit events logged to `.runs/`

## 6) API Analysis

```bash
curl -X POST http://localhost:8000/api/analyse \
  -H "Content-Type: application/json" \
  -d '{"contract_text": "1. INDEMNIFICATION: Party shall indemnify...", "no_human_gate": true}' \
  | python3 -m json.tool
```

## 7) Next.js UI

```bash
cd ui && npm run dev
# → http://localhost:3000
```

- Upload a contract → watch real-time agent feed
- See risk distribution chart
- View audit trail with Weilchain transaction links

## 8) Verify On-Chain Audit Trail

Check latest run:
```bash
ls -1t .runs/*.jsonl | head -1 | xargs head -5
```

Each event has:
- `weilchain_tx_status`, `weilchain_batch_id`, `weilchain_block_height`

## 9) WASM Applet Verification

Pre-compiled WASM artifacts:
```bash
ls -la src/applets/wasm/
```

Deployed applet IDs in `.env`:
```bash
grep APPLET_ID .env
```

Both deployed and **Finalized** on Weilchain (block ~3879551).

## 10) Hackathon Requirement Mapping

| Requirement | Where | Lines |
|---|---|---|
| **Agentic framework** (LangGraph) | `src/agent/graph.py`, `src/agent/nodes.py` | 280+ |
| **Custom control loop** | `src/agent/control_loop.py` | 632 |
| **Weilchain audit logging** | `src/agent/audit.py` | 207 |
| **MCP applet execution** | `src/tools/router.py` | 400 |
| **WIDL interfaces** | `src/applets/*.widl` | 53 |
| **Rust WASM applets** | `rust_applets/*/src/lib.rs` | 284 |
| **weil_ai SDK** (WeilAgent, middleware, auth) | `src/agent/audit.py`, `src/api/server.py` | — |
| **weil_wallet SDK** (WeilClient, contracts) | `src/tools/router.py` | — |
| **Human-in-the-loop gate** | `src/agent/control_loop.py:_node_human_gate` | ~30 |
| **Fail-closed behavior** | `src/tools/router.py`, tests | — |
| **Dual audit trail** (local JSONL + on-chain) | `src/agent/audit.py` | 207 |
| **Cryptographic auth** (wallet signatures) | `src/agent/audit.py:get_auth_headers()` | — |
