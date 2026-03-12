#!/bin/bash
# ============================================================
#  LexAudit — Full Deploy Pipeline
#  1. Build Rust WASM applets
#  2. Deploy to Weilchain Asia-South POD (marauder)
#  Usage:  ./scripts/deploy.sh
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

POD_URL="https://marauder.weilliptic.ai"
SENTINEL_URL="https://sentinel.weilliptic.ai"
WIDL_DIR="src/applets"
WASM_DIR="src/applets/wasm"
CONFIG="src/applets/lexaudit.yaml"

echo "═══════════════════════════════════════════"
echo "  LexAudit — Deploy Pipeline"
echo "  POD:      $POD_URL"
echo "  Sentinel: $SENTINEL_URL"
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
echo "  ✓ clause_extractor.wasm: $(wc -c < $WASM_DIR/clause_extractor.wasm) bytes"
echo "  ✓ risk_scorer.wasm:      $(wc -c < $WASM_DIR/risk_scorer.wasm) bytes"

# --- Step 3: Install JS SDK (if needed) ---
if [ ! -d "node_modules/@weilliptic" ]; then
  echo ""
  echo "▸ Installing @weilliptic/weil-sdk..."
  npm install
fi

# --- Step 4: Deploy to Weilchain via JS SDK ---
echo ""
echo "▸ Deploying to Weilchain (marauder POD)..."
node scripts/deploy_applets.mjs --pod asia-south

# --- Step 5: Deploy via weilliptic CLI (alternative) ---
# Uncomment these if using the weilliptic CLI instead of the JS SDK:
#
# echo "📦 Deploying clause_extractor..."
# weilliptic deploy \
#   --widl-file $WIDL_DIR/clause_extractor.widl \
#   --file-path $WASM_DIR/clause_extractor.wasm \
#   --config-file $CONFIG \
#   --pod-url $POD_URL \
#   --node-url $SENTINEL_URL \
#   --wallet private_key.wc
#
# echo "📦 Deploying risk_scorer..."
# weilliptic deploy \
#   --widl-file $WIDL_DIR/risk_scorer.widl \
#   --file-path $WASM_DIR/risk_scorer.wasm \
#   --config-file $CONFIG \
#   --pod-url $POD_URL \
#   --node-url $SENTINEL_URL \
#   --wallet private_key.wc

echo ""
echo "═══════════════════════════════════════════"
echo "  ✅ Both applets deployed to marauder POD!"
echo "  View at: $POD_URL"
echo "═══════════════════════════════════════════"
