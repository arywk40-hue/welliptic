#!/usr/bin/env python3
"""Encode a Weilchain wallet file to base64 for Railway deployment.

Usage:
    python scripts/encode_wallet.py

Reads private_key.wc from the repo root and outputs the base64-encoded content.
Set the output as WALLET_B64 environment variable in Railway.
"""

import base64
from pathlib import Path


def main():
    wallet_path = Path(__file__).parent.parent / "private_key.wc"

    if not wallet_path.exists():
        print(f"❌ Wallet file not found: {wallet_path}")
        print("   Create a private_key.wc file in the repo root first.")
        return 1

    with open(wallet_path, "rb") as f:
        wallet_bytes = f.read()

    encoded = base64.b64encode(wallet_bytes).decode("utf-8")

    print("✅ Wallet encoded successfully!")
    print("\nSet this as WALLET_B64 environment variable in Railway:\n")
    print(encoded)
    print("\nThe wallet will be decoded at startup and written to private_key.wc")

    return 0


if __name__ == "__main__":
    exit(main())
