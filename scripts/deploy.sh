#!/bin/bash
# ============================================================
#  LexAudit — Full Deploy Pipeline
#  1. Build Rust WASM applets
#  2. Deploy to Weilchain via JS SDK
#  Usage:  ./scripts/deploy.sh
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

echo "═══════════════════════════════════════════"
echo "  LexAudit — Deploy Pipeline"
echo "═══════════════════════════════════════════"

# --- Step 1: Pre-flight checks ---
echo ""
echo "▸ Checking prerequisites..."

if [ ! -f ".env" ]; then
  echo "  ✗ Missing .env — copy .env.example and fill in values"
  exit 1
fi
source .env

if [ ! -f "private_key.wc" ]; then
  echo "  ✗ Missing private_key.wc — generate with:"
  echo "    python3 -c \"import os; open('private_key.wc','w').write(os.urandom(32).hex())\""
  exit 1
fi

echo "  ✓ .env loaded"
echo "  ✓ Wallet key found"

# --- Step 2: Build WASM ---
echo ""
echo "▸ Building WASM applets..."
cd rust_applets
./build.sh
cd "$PROJECT_DIR"
echo "  ✓ clause_extractor.wasm: $(wc -c < src/applets/wasm/clause_extractor.wasm) bytes"
echo "  ✓ risk_scorer.wasm:      $(wc -c < src/applets/wasm/risk_scorer.wasm) bytes"

# --- Step 3: Install JS SDK (if needed) ---
if [ ! -d "node_modules/@weilliptic" ]; then
  echo ""
  echo "▸ Installing @weilliptic/weil-sdk..."
  npm install
fi

# --- Step 4: Deploy to Weilchain ---
echo ""
echo "▸ Deploying to Weilchain sentinel..."
node scripts/deploy_applets.mjs

echo ""
echo "═══════════════════════════════════════════"
echo "  ✓ Deploy complete!"
echo "  → Update .env with the applet IDs above"
echo "  → Then run: make serve"
echo "═══════════════════════════════════════════"
