"""LexAudit — FastAPI server entry point.

Usage:
    python server.py              # Start on 0.0.0.0:8000
    python server.py --port 9000  # Custom port
"""
from __future__ import annotations

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
    host = os.getenv("LEXAUDIT_HOST", "0.0.0.0")
    port = int(os.getenv("LEXAUDIT_PORT", "8000"))
    print(f"🔍 LexAudit API starting on http://{host}:{port}")
    uvicorn.run("server:app", host=host, port=port, reload=False)
