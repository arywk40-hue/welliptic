#!/bin/bash
# ============================================================
#  Verify LexAudit deployment — checks all components
# ============================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$(dirname "$SCRIPT_DIR")"

echo "═══════════════════════════════════════════"
echo "  LexAudit — Deployment Verification"
echo "═══════════════════════════════════════════"
PASS=0; FAIL=0

check() {
  if eval "$2" >/dev/null 2>&1; then
    echo "  ✓ $1"
    PASS=$((PASS + 1))
  else
    echo "  ✗ $1"
    FAIL=$((FAIL + 1))
  fi
}

echo ""
echo "▸ Environment"
check ".env exists"              "test -f .env"
check "private_key.wc exists"    "test -f private_key.wc"
check "ANTHROPIC_API_KEY set"    "grep -q 'ANTHROPIC_API_KEY=sk-' .env"
check "WEILCHAIN_NODE_URL set"   "grep -q 'sentinel.unweil.me' .env"
check "CLAUSE_EXTRACTOR set"     "grep -q 'CLAUSE_EXTRACTOR_APPLET_ID=aaaa' .env"
check "RISK_SCORER set"          "grep -q 'RISK_SCORER_APPLET_ID=aaaa' .env"

echo ""
echo "▸ WASM Artifacts"
check "clause_extractor.wasm"    "test -f src/applets/wasm/clause_extractor.wasm"
check "risk_scorer.wasm"         "test -f src/applets/wasm/risk_scorer.wasm"

echo ""
echo "▸ WIDL Definitions"
check "clause_extractor.widl"    "test -f src/applets/clause_extractor.widl"
check "risk_scorer.widl"         "test -f src/applets/risk_scorer.widl"

echo ""
echo "▸ Python Imports"
check "src.config imports"       "python3 -c 'from src.config import load_settings'"
check "src.types imports"        "python3 -c 'from src.types import Clause, RiskScore'"
check "src.agent imports"        "python3 -c 'from src.agent.control_loop import run_lexaudit'"
check "src.tools imports"        "python3 -c 'from src.tools.router import ToolRouter'"
check "src.api imports"          "python3 -c 'from src.api.server import app'"

echo ""
echo "▸ Tests"
check "pytest runs clean"        "python3 -m pytest tests/ -q --tb=no"

echo ""
echo "▸ Server (if running)"
if curl -sf http://localhost:8000/api/health >/dev/null 2>&1; then
  check "API health endpoint"    "curl -sf http://localhost:8000/api/health"
  HEALTH=$(curl -sf http://localhost:8000/api/health)
  echo "    Response: $HEALTH"
else
  echo "  ○ Server not running (skipped)"
fi

echo ""
echo "═══════════════════════════════════════════"
echo "  Results: $PASS passed, $FAIL failed"
echo "═══════════════════════════════════════════"

[ $FAIL -eq 0 ] && exit 0 || exit 1
