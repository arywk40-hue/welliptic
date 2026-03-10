"""LexAudit — FastAPI server entry point.

Usage:
    python server.py              # Start on 0.0.0.0:8000
    python server.py --port 9000  # Custom port
"""
from __future__ import annotations

import base64
import os
import sys
from pathlib import Path

# Ensure project root is on sys.path so `from src.…` works
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import uvicorn

from src.api.server import app  # noqa: F401 — re-export for uvicorn


if __name__ == "__main__":
    # Decode WALLET_B64 environment variable if present (Railway deployment)
    wallet_b64 = os.getenv("WALLET_B64", "").strip()
    if wallet_b64:
        try:
            wallet_bytes = base64.b64decode(wallet_b64)
            wallet_path = ROOT / "private_key.wc"
            wallet_path.write_bytes(wallet_bytes)
            print(f"✅ Decoded wallet from WALLET_B64 to {wallet_path}")
        except Exception as exc:
            print(f"⚠️ Failed to decode WALLET_B64: {exc}")

    host = os.getenv("LEXAUDIT_HOST", "0.0.0.0")
    # Support both PORT (Railway standard) and LEXAUDIT_PORT
    port = int(os.getenv("PORT", os.getenv("LEXAUDIT_PORT", "8000")))
    print(f"🔍 LexAudit API starting on http://{host}:{port}")
    uvicorn.run("server:app", host=host, port=port, reload=False)
