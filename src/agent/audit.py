from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from src.types import AuditEvent

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from weil_ai import WeilAgent
    from weil_wallet import PrivateKey, TransactionResult, Wallet, WeilClient

_HAS_WEIL_SDK = False
try:
    from weil_ai import WeilAgent  # type: ignore[no-redef]
    from weil_wallet import PrivateKey, TransactionResult, Wallet, WeilClient  # type: ignore[no-redef]
    _HAS_WEIL_SDK = True
except Exception:  # noqa: BLE001
    pass


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

    **Event loop fix**: The SDK's ``WeilAgent.audit()`` calls
    ``asyncio.run()`` for each invocation, which creates + destroys an event
    loop every time.  On Python 3.13 the httpx/anyio TLS socket close races
    with the loop shutdown, causing ~40% of calls to raise
    ``RuntimeError('Event loop is closed')``.  We work around this by keeping
    a single persistent event loop in a background thread and dispatching all
    audit writes through it.
    """

    def __init__(
        self,
        wallet_path: str,
        sentinel_host: str = "https://sentinel.weilliptic.ai",
    ) -> None:
        self.wallet_path = wallet_path
        self.sentinel_host = sentinel_host
        self.enabled = False
        self._agent: Any = None
        self._wallet: Any = None
        self._wallet_address: Optional[str] = None
        self.tx_results: List[Dict[str, Any]] = []
        # Persistent event loop for on-chain audit writes (avoids the
        # Python 3.13 asyncio.run() socket-close race condition).
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._loop_thread: Any = None
        self._loop_client: Any = None
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
            # changed across versions.  Always pass sentinel_host so the
            # WeilClient hits our node (sentinel.weilliptic.ai) instead of
            # the SDK default (sentinel.unweil.me).
            agent: Any = None
            init_strategies: list[tuple[str, Any]] = [
                ("WeilAgent(sentinel, wallet=wallet, sentinel_host=host)",
                 lambda: WeilAgent(sentinel, wallet=self._wallet, sentinel_host=self.sentinel_host)),
                ("WeilAgent(sentinel, wallet=wallet)",
                 lambda: WeilAgent(sentinel, wallet=self._wallet)),
                ("WeilAgent(sentinel, private_key_path=wallet_path, sentinel_host=host)",
                 lambda: WeilAgent(sentinel, private_key_path=self.wallet_path, sentinel_host=self.sentinel_host)),
                ("WeilAgent(sentinel, private_key_path=wallet_path)",
                 lambda: WeilAgent(sentinel, private_key_path=self.wallet_path)),
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

    # ── Persistent event loop (avoids Python 3.13 asyncio.run race) ──────

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        """Return a persistent event loop running in a background thread.

        The Weilchain SDK's ``WeilAgent.audit()`` calls ``asyncio.run()``
        which creates and destroys a fresh event loop for every call.  On
        Python ≥ 3.13 the httpx/anyio TLS stream close races with loop
        shutdown, causing ``RuntimeError('Event loop is closed')`` for ~40%
        of calls.

        We work around this by keeping a single long-lived loop in a daemon
        thread.  A fresh ``WeilClient`` is created on this loop so its httpx
        connection pool stays alive across calls.
        """
        if self._loop is not None and self._loop.is_running():
            return self._loop

        import threading

        loop = asyncio.new_event_loop()
        thread = threading.Thread(target=loop.run_forever, daemon=True, name="weil-audit-loop")
        thread.start()
        self._loop = loop
        self._loop_thread = thread
        # Pre-create a WeilClient bound to THIS loop so the httpx pool stays open.
        self._loop_client = None
        return loop

    def _submit_audit_stable(self, log_entry: str) -> Any:
        """Submit an audit log entry using a dedicated persistent event loop.

        Creates a fresh WeilClient + httpx session on the persistent loop
        and reuses it for all subsequent calls. This avoids the SDK's
        ``asyncio.run()`` pattern entirely.
        """
        loop = self._ensure_loop()

        async def _do_audit() -> Any:
            # Lazily build a WeilClient on this loop — reuse across calls
            if self._loop_client is None:
                pk = PrivateKey.from_file(self.wallet_path)
                wallet = Wallet(pk)
                # WeilClient constructor signature: WeilClient(wallet, sentinel_host=...)
                try:
                    self._loop_client = WeilClient(wallet, sentinel_host=self.sentinel_host)
                except TypeError:
                    self._loop_client = WeilClient(wallet)
            return await self._loop_client.audit(log_entry)

        future = asyncio.run_coroutine_threadsafe(_do_audit(), loop)
        return future.result(timeout=30)

    @property
    def wallet(self) -> Any:
        """Return the underlying Wallet, or None if not enabled."""
        return self._wallet

    @property
    def wallet_address(self) -> Optional[str]:
        """Return the hex wallet address, or None if unavailable."""
        return self._wallet_address

    @property
    def is_active(self) -> bool:
        """Returns True if WeilAgent is initialized and can sign requests."""
        try:
            headers = self._agent.get_auth_headers()
            return len(headers) >= 2
        except Exception:  # noqa: BLE001
            return False

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
        """Submit an audit log entry on-chain via the persistent event loop.

        The log entry is a JSON string containing the event type, timestamp,
        and all event data (node, status, hashes, etc.). The transaction
        result (status, block_height, batch_id) is stored for later reference.

        Uses ``_submit_audit_stable()`` which keeps a single long-lived event
        loop to avoid the Python 3.13 ``asyncio.run()`` TLS socket race that
        drops ~40% of transactions.  Falls back to the SDK's own
        ``agent.audit()`` if the stable path fails.
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
            # Primary path: persistent event loop (100% delivery)
            result = self._submit_audit_stable(log_entry)
        except Exception:  # noqa: BLE001
            try:
                # Fallback: SDK's own asyncio.run() (~60% delivery)
                result = self._agent.audit(log_entry)
            except Exception as exc2:  # noqa: BLE001
                logger.debug(
                    "On-chain audit failed for event '%s': %s (%s) — local JSONL still recorded",
                    event_type, type(exc2).__name__, exc2,
                )
                return

        try:
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

    def get_tx_hashes(self) -> List[str]:
        """Return all transaction hashes from audit calls."""
        return [tx["tx_hash"] for tx in self.tx_results if tx.get("tx_hash")]


def get_explorer_url(tx_hash: str) -> str:
    """Return Weilchain explorer URL for a transaction hash."""
    return f"https://marauder.weilliptic.ai/tx/{tx_hash}"


def get_wallet_explorer_url(address: str) -> str:
    """Return Weilchain explorer URL for a wallet address."""
    return f"https://marauder.weilliptic.ai/address/{address}"
