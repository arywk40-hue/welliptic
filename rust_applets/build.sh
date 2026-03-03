#!/bin/bash
set -e
echo "Building clause_extractor..."
cd clause_extractor
cargo build --release --target wasm32-unknown-unknown
cd ..

echo "Building risk_scorer..."
cd risk_scorer
cargo build --release --target wasm32-unknown-unknown
cd ..

echo "Copying .wasm files..."
mkdir -p ../src/applets/wasm
cp target/wasm32-unknown-unknown/release/clause_extractor.wasm \
   ../src/applets/wasm/
cp target/wasm32-unknown-unknown/release/risk_scorer.wasm \
   ../src/applets/wasm/

echo "Done! .wasm files in src/applets/wasm/"
