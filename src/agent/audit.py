from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.types import AuditEvent

logger = logging.getLogger(__name__)

try:
    from weil_ai import WeilAgent
    from weil_wallet import PrivateKey, TransactionResult, Wallet, WeilClient
    _HAS_WEIL_SDK = True
except Exception:  # noqa: BLE001
    _HAS_WEIL_SDK = False


def stable_hash(value: Any) -> str:
    try:
        payload = json.dumps(value, sort_keys=True, ensure_ascii=True)
    except TypeError:
        payload = str(value)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def bounded_preview(text: str, limit: int = 120) -> str:
    trimmed = " ".join(text.strip().split())
    if len(trimmed) <= limit:
        return trimmed
    return trimmed[:limit] + "..."


class AuditLogger:
    def __init__(self, runs_dir: Path, session_id: str) -> None:
        self.runs_dir = runs_dir
        self.session_id = session_id
        self.events: List[AuditEvent] = []
        self.step_index = 0
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.jsonl_path = self.runs_dir / f"{self.session_id}.jsonl"

    def emit(
        self,
        *,
        event_type: str,
        node: str,
        status: str = "ok",
        model: Optional[str] = None,
        tool_name: Optional[str] = None,
        input_payload: Optional[Any] = None,
        output_payload: Optional[Any] = None,
        error: Optional[str] = None,
        latency_ms: int = 0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AuditEvent:
        event = AuditEvent(
            step_index=self.step_index,
            event_type=event_type,
            timestamp=int(time.time()),
            node=node,
            input_hash=stable_hash(input_payload) if input_payload is not None else None,
            output_hash=stable_hash(output_payload) if output_payload is not None else None,
            latency_ms=latency_ms,
            model=model,
            tool_name=tool_name,
            status=status,
            error=error,
            metadata=metadata or {},
        )
        self.step_index += 1
        self.events.append(event)
        with self.jsonl_path.open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(asdict(event), ensure_ascii=True) + "\n")
        return event

    def summary(self, output_path: Path, *, final_status: str, extra: Dict[str, Any]) -> Dict[str, Any]:
        payload = {
            "session_id": self.session_id,
            "event_count": len(self.events),
            "final_status": final_status,
            "events_path": str(self.jsonl_path),
            "extra": extra,
        }
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return payload


class WeilAuditLogger:
    """On-chain audit logger using the Weilchain ADK (``weil_ai.WeilAgent``).

    Wraps a lightweight sentinel agent with a Weil wallet identity using the
    ``WeilAgent`` proxy from the ADK.  Every audit event is submitted on-chain
    via ``WeilAgent.audit(log)`` which handles both sync and async contexts
    internally, so callers don't need to manage event loops.

    The ``WeilAgent`` additionally exposes:

    * ``get_auth_headers()`` — signed MCP auth headers (used by the HTTP
      MCP client in ``router.py``).
    * ``weil_wallet`` — the underlying ``Wallet`` instance.

    Falls back gracefully to local-only JSONL auditing if the SDK is missing,
    the wallet file doesn't exist, or the chain is unreachable.
    """

    def __init__(self, wallet_path: str) -> None:
        self.wallet_path = wallet_path
        self.enabled = False
        self._agent: Any = None
        self._wallet: Any = None
        self._wallet_address: Optional[str] = None
        self.tx_results: List[Dict[str, Any]] = []
        self._initialize()

    @staticmethod
    def _resolve_wallet_address(wallet: Any) -> Optional[str]:
        """Extract a hex wallet address string from a ``Wallet`` object.

        The ``weil_wallet.Wallet`` SDK does **not** expose a ``.address``
        attribute.  The canonical path is::

            wallet.get_public_key()          # → coincurve.PublicKey
                  .format(compressed=True)   # → bytes (33 bytes)
                  .hex()                     # → hex string

        We try multiple strategies so this never crashes even if the SDK
        changes its API surface.
        """
        strategies: list[tuple[str, Any]] = [
            # Strategy 1 (canonical): compressed public key hex
            ("get_public_key().format().hex()",
             lambda w: w.get_public_key().format(compressed=True).hex()),
            # Strategy 2: uncompressed public key hex
            ("get_public_key().format(False).hex()",
             lambda w: w.get_public_key().format(compressed=False).hex()),
            # Strategy 3: maybe a future .address property
            ("address", lambda w: w.address),
            # Strategy 4: maybe a future .get_address() method
            ("get_address()", lambda w: w.get_address()),
            # Strategy 5: repr/str fallback
            ("repr()", lambda w: repr(w)),
        ]
        for label, fn in strategies:
            try:
                result = fn(wallet)
                if isinstance(result, str) and len(result) > 10:
                    return result
            except Exception:  # noqa: BLE001
                continue
        return None

    def _initialize(self) -> None:
        if not _HAS_WEIL_SDK:
            return

        key_path = Path(self.wallet_path)
        if not key_path.is_file():
            return

        try:
            pk = PrivateKey.from_file(key_path)
            self._wallet = Wallet(pk)

            # Resolve the wallet address safely (never crashes).
            self._wallet_address = self._resolve_wallet_address(self._wallet)
            if self._wallet_address:
                logger.info("Weil wallet address: %s…", self._wallet_address[:16])
            else:
                logger.warning("Could not resolve wallet address — continuing without it")

            # Create a lightweight sentinel object that WeilAgent will wrap.
            # WeilAgent proxies all Weil-specific calls (audit, get_auth_headers)
            # while forwarding everything else to this inner object.
            #
            # NOTE: The SDK internally accesses attributes like ``pod_counter``
            # on the inner agent.  We provide them as no-op defaults so the
            # proxy never raises ``AttributeError: 'str' object has no
            # attribute 'pod_counter'`` (which happens when a bare string is
            # passed instead of an object).
            class _LexAuditSentinel:
                """Inner agent identity for the LexAudit on-chain auditor."""
                name = "lexaudit-auditor"
                # Attributes that WeilAgent may probe on the inner object:
                pod_counter = 0
                pods = []
                model = None
                tools = []

            sentinel = _LexAuditSentinel()

            # Try multiple WeilAgent constructor signatures — the SDK has
            # changed across versions.
            agent: Any = None
            init_strategies: list[tuple[str, Any]] = [
                ("WeilAgent(sentinel, wallet=wallet)",
                 lambda: WeilAgent(sentinel, wallet=self._wallet)),
                ("WeilAgent(sentinel, self._wallet)",
                 lambda: WeilAgent(sentinel, self._wallet)),
                ("WeilAgent(sentinel)",
                 lambda: WeilAgent(sentinel)),
            ]
            for label, factory in init_strategies:
                try:
                    agent = factory()
                    logger.info("WeilAgent created via %s", label)
                    break
                except Exception as exc:  # noqa: BLE001
                    logger.debug(
                        "WeilAgent init strategy '%s' failed: %s (%s)",
                        label, type(exc).__name__, exc,
                    )
                    continue

            if agent is not None:
                self._agent = agent
                self.enabled = True
            else:
                logger.warning(
                    "All WeilAgent init strategies failed — on-chain audit disabled "
                    "(local JSONL still active)"
                )
        except Exception as exc:  # noqa: BLE001
            self.enabled = False
            self._agent = None
            logger.warning(
                "WeilAuditLogger initialization failed: %s (%s) — "
                "on-chain audit disabled, local JSONL still active",
                type(exc).__name__, exc,
            )

    @property
    def wallet(self) -> Any:
        """Return the underlying Wallet, or None if not enabled."""
        return self._wallet

    @property
    def wallet_address(self) -> Optional[str]:
        """Return the hex wallet address, or None if unavailable."""
        return self._wallet_address

    def get_auth_headers(self) -> Dict[str, str]:
        """Return signed auth headers for MCP requests.

        These headers (X-Wallet-Address, X-Signature, X-Message, X-Timestamp)
        allow the Weilchain MCP server to cryptographically verify the caller
        identity using ``weil_middleware()``.
        """
        if not self.enabled or self._agent is None:
            return {}
        try:
            return self._agent.get_auth_headers()
        except Exception:  # noqa: BLE001
            return {}

    def emit(self, event_type: str, data: Dict[str, Any]) -> None:
        """Submit an audit log entry on-chain via WeilAgent.audit().

        The log entry is a JSON string containing the event type, timestamp,
        and all event data (node, status, hashes, etc.). The transaction
        result (status, block_height, batch_id) is stored for later reference.

        WeilAgent.audit() internally handles async/sync context switching,
        so this method is safe to call from any context.
        """
        if not self.enabled or self._agent is None:
            return

        log_entry = json.dumps(
            {
                "event": event_type,
                "data": data,
                "timestamp": int(time.time()),
            },
            sort_keys=True,
            ensure_ascii=True,
        )

        try:
            result = self._agent.audit(log_entry)
            tx_hash = None
            for key in ("tx_hash", "transaction_hash", "hash"):
                value = getattr(result, key, None)
                if value:
                    tx_hash = str(value)
                    break
            self.tx_results.append(
                {
                    "event_type": event_type,
                    "status": str(getattr(result, "status", "unknown")),
                    "block_height": getattr(result, "block_height", None),
                    "batch_id": getattr(result, "batch_id", None),
                    "tx_hash": tx_hash,
                }
            )
        except AttributeError as exc:
            # SDK object-model mismatch (e.g. 'str' has no attribute 'pod_counter')
            logger.debug(
                "On-chain audit AttributeError for '%s': %s — "
                "this is expected if the SDK inner agent shape changed",
                event_type, exc,
            )
        except Exception as exc:  # noqa: BLE001
            # Fail open — local JSONL audit still captures everything.
            logger.debug(
                "On-chain audit failed for event '%s': %s (%s) — local JSONL still recorded",
                event_type, type(exc).__name__, exc,
            )

    def get_tx_hashes(self) -> List[str]:
        """Return all transaction hashes from audit calls."""
        return [tx["tx_hash"] for tx in self.tx_results if tx.get("tx_hash")]


def get_explorer_url(tx_hash: str) -> str:
    """Return Weilchain explorer URL for a transaction hash."""
    return f"https://explorer.weilliptic.ai/tx/{tx_hash}"


def get_wallet_explorer_url(address: str) -> str:
    """Return Weilchain explorer URL for a wallet address."""
    return f"https://explorer.weilliptic.ai/address/{address}"
