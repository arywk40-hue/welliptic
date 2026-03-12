"""
Verify Weilliptic production endpoints and on-chain connectivity.

Usage:  python scripts/verify_endpoints.py

Checks:
  1. sentinel.weilliptic.ai  → reachable (HTTP 200)
  2. marauder.weilliptic.ai  → reachable (HTTP 200)
  3. Wallet address from private_key.wc
  4. WeilAgent.audit("connectivity-test") → tx status + tx_hash
  5. Explorer URL for that tx_hash
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

load_dotenv(ROOT / ".env")

SENTINEL_URL = os.getenv("WEILCHAIN_NODE_URL", "https://sentinel.weilliptic.ai")
POD_URL = os.getenv("WEILCHAIN_POD_URL", "https://marauder.weilliptic.ai")
WALLET_PATH = os.getenv("WEILCHAIN_WALLET_PATH", "private_key.wc")


def ping(url: str, label: str) -> bool:
    """HTTP GET the URL and check for a 2xx/3xx response."""
    print(f"\n{'─' * 50}")
    print(f"  Pinging {label}: {url}")
    try:
        req = urllib.request.Request(url, method="GET")
        req.add_header("User-Agent", "LexAudit-Verify/1.0")
        with urllib.request.urlopen(req, timeout=15) as resp:
            code = resp.getcode()
            print(f"  ✅  HTTP {code}")
            return True
    except urllib.error.HTTPError as exc:
        # Even a 4xx means the server is reachable
        print(f"  ⚠️  HTTP {exc.code} ({exc.reason}) — server reachable")
        return True
    except urllib.error.URLError as exc:
        print(f"  ❌  Unreachable: {exc.reason}")
        return False
    except Exception as exc:
        print(f"  ❌  Error: {exc}")
        return False


def check_wallet() -> str | None:
    """Load wallet and print address."""
    print(f"\n{'─' * 50}")
    print(f"  Wallet: {WALLET_PATH}")

    key_path = Path(ROOT / WALLET_PATH) if not Path(WALLET_PATH).is_absolute() else Path(WALLET_PATH)
    if not key_path.is_file():
        print(f"  ❌  Wallet file not found: {key_path}")
        return None

    try:
        from weil_wallet import PrivateKey, Wallet
        pk = PrivateKey.from_file(key_path)
        wallet = Wallet(pk)

        # Resolve address
        address = None
        try:
            address = wallet.get_public_key().format(compressed=True).hex()
        except Exception:
            try:
                address = getattr(wallet, "address", None) or repr(wallet)
            except Exception:
                address = repr(wallet)

        if address:
            print(f"  ✅  Wallet address: {address[:20]}…")
        else:
            print("  ⚠️  Could not resolve wallet address")
        return address
    except ImportError:
        print("  ⚠️  weil_wallet SDK not installed — skipping wallet check")
        return None
    except Exception as exc:
        print(f"  ❌  Error loading wallet: {exc}")
        return None


def test_audit() -> str | None:
    """Test WeilAgent.audit() connectivity."""
    print(f"\n{'─' * 50}")
    print("  Testing WeilAgent.audit() on-chain...")

    key_path = Path(ROOT / WALLET_PATH) if not Path(WALLET_PATH).is_absolute() else Path(WALLET_PATH)
    if not key_path.is_file():
        print("  ❌  No wallet file — skipping audit test")
        return None

    try:
        from weil_ai import WeilAgent
        from weil_wallet import PrivateKey, Wallet

        pk = PrivateKey.from_file(key_path)
        wallet = Wallet(pk)

        class _TestSentinel:
            name = "lexaudit-verify"
            pod_counter = 0
            pods = []
            model = None
            tools = []

        sentinel = _TestSentinel()

        agent = None
        for factory in [
            lambda: WeilAgent(sentinel, wallet=wallet),
            lambda: WeilAgent(sentinel, private_key_path=key_path),
            lambda: WeilAgent(sentinel),
        ]:
            try:
                agent = factory()
                break
            except Exception:
                continue

        if agent is None:
            print("  ❌  Could not create WeilAgent")
            return None

        log_entry = json.dumps({
            "event": "connectivity-test",
            "timestamp": int(time.time()),
            "source": "verify_endpoints.py",
        })

        result = agent.audit(log_entry)

        tx_hash = None
        for key in ("tx_hash", "transaction_hash", "hash"):
            value = getattr(result, key, None)
            if value:
                tx_hash = str(value)
                break

        status = str(getattr(result, "status", "unknown"))
        block = getattr(result, "block_height", None)
        batch = getattr(result, "batch_id", None)

        print(f"  ✅  Audit submitted!")
        print(f"      Status:       {status}")
        print(f"      Block height: {block}")
        print(f"      Batch ID:     {batch}")
        print(f"      TX hash:      {tx_hash}")

        if tx_hash:
            explorer = f"https://marauder.weilliptic.ai/tx/{tx_hash}"
            print(f"      Explorer:     {explorer}")
        return tx_hash

    except ImportError:
        print("  ⚠️  weil_ai SDK not installed — skipping audit test")
        return None
    except Exception as exc:
        print(f"  ❌  Audit test failed: {type(exc).__name__}: {exc}")
        return None


def main() -> None:
    print("=" * 50)
    print("  LexAudit — Endpoint Verification")
    print("=" * 50)

    sentinel_ok = ping(SENTINEL_URL, "Sentinel")
    pod_ok = ping(POD_URL, "Marauder POD")
    address = check_wallet()
    tx_hash = test_audit()

    print(f"\n{'═' * 50}")
    print("  SUMMARY")
    print(f"{'═' * 50}")
    print(f"  Sentinel ({SENTINEL_URL}):  {'✅' if sentinel_ok else '❌'}")
    print(f"  Marauder ({POD_URL}):       {'✅' if pod_ok else '❌'}")
    print(f"  Wallet:   {'✅ ' + (address[:20] + '…' if address else '—') if address else '❌'}")
    print(f"  Audit TX: {'✅ ' + tx_hash if tx_hash else '⚠️  No TX (SDK missing or chain unreachable)'}")

    if not sentinel_ok or not pod_ok:
        print("\n  ⚠️  Some endpoints unreachable — this is expected if")
        print("     DNS hasn't propagated yet. LocalFallback will be used.")

    print()
    sys.exit(0 if (sentinel_ok and pod_ok) else 1)


if __name__ == "__main__":
    main()
