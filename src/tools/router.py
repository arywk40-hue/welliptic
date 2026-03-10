from __future__ import annotations

import asyncio
import inspect
import json
import logging
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Protocol

from src.config import Settings
from src.types import ToolContext, ToolResult

logger = logging.getLogger(__name__)

try:
    from weil_wallet import PrivateKey, Wallet, WeilClient

    _HAS_WEIL_WALLET = True
except Exception:  # noqa: BLE001
    _HAS_WEIL_WALLET = False

# Lazy import to avoid circular dependency — resolved at runtime.
_LocalFallbackMCPClient: type | None = None


def _get_local_fallback_class() -> type:
    global _LocalFallbackMCPClient
    if _LocalFallbackMCPClient is None:
        from src.tools.local_fallback import LocalFallbackMCPClient
        _LocalFallbackMCPClient = LocalFallbackMCPClient
    return _LocalFallbackMCPClient


class ToolExecutionError(RuntimeError):
    pass


class McpUnavailableError(ToolExecutionError):
    pass


@dataclass(frozen=True)
class ToolSpec:
    applet_id: str
    interface: str
    default_method: str


class MCPClient(Protocol):
    def is_available(self) -> bool:
        ...

    def discover_tools(self) -> Dict[str, ToolSpec]:
        ...

    def call_tool(
        self,
        *,
        tool_name: str,
        method_name: str,
        payload: Dict[str, Any],
        timeout_seconds: float,
        tool_spec: ToolSpec,
    ) -> Dict[str, Any]:
        ...


class WeilchainHTTPMCPClient:
    """HTTP MCP client bootstrap for deployed Weilchain applets.

    When a ``weil_auth_headers`` dict is provided (from
    ``WeilAgent.get_auth_headers()``), every MCP request includes the
    cryptographic wallet-signature headers required by ``weil_middleware()``.
    """

    def __init__(
        self,
        *,
        node_url: str,
        tool_specs: Dict[str, ToolSpec],
        weil_auth_headers: Optional[Dict[str, str]] = None,
    ) -> None:
        self.node_url = node_url.rstrip("/")
        self._tool_specs = tool_specs
        self._weil_auth_headers = weil_auth_headers or {}

    def is_available(self) -> bool:
        return bool(self.node_url and self._tool_specs)

    def discover_tools(self) -> Dict[str, ToolSpec]:
        # Tool IDs are mapped from local config and validated at bootstrap.
        return dict(self._tool_specs)

    def call_tool(
        self,
        *,
        tool_name: str,
        method_name: str,
        payload: Dict[str, Any],
        timeout_seconds: float,
        tool_spec: ToolSpec,
    ) -> Dict[str, Any]:
        if not tool_spec.applet_id:
            raise ToolExecutionError(f"No applet ID mapped for tool '{tool_name}'")

        endpoint = f"{self.node_url}/v1/applets/{tool_spec.applet_id}/invoke"
        body = {
            "interface": tool_spec.interface,
            "method": method_name,
            "tool": tool_name,
            "params": payload,
            "input": payload,
        }

        req = urllib.request.Request(
            endpoint,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                **self._weil_auth_headers,
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
                raw = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise ToolExecutionError(
                    f"MCP applet not deployed yet (HTTP 404 for {tool_spec.applet_id}) "
                    f"— using LocalFallback (correct for dev)"
                ) from exc
            raise ToolExecutionError(
                f"MCP HTTP {exc.code} for applet {tool_spec.applet_id}: {exc.reason}"
            ) from exc
        except urllib.error.URLError as exc:
            raise ToolExecutionError(
                f"MCP endpoint unreachable ({exc.reason}) — will fall back to local"
            ) from exc

        try:
            envelope = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ToolExecutionError("MCP response was not valid JSON") from exc

        if not isinstance(envelope, dict):
            raise ToolExecutionError("MCP response envelope must be an object")

        return envelope


class WeilchainSDKMCPClient:
    """SDK-based MCP applet caller using ``weil_wallet.WeilClient``."""

    def __init__(
        self,
        *,
        node_url: str,
        wallet_path: str,
        tool_specs: Dict[str, ToolSpec],
    ) -> None:
        if not _HAS_WEIL_WALLET:
            raise McpUnavailableError("weil_wallet SDK is not installed")

        key_path = Path(wallet_path)
        if not key_path.is_file():
            raise McpUnavailableError(
                f"Weilchain wallet file not found: {wallet_path}"
            )

        self._tool_specs = tool_specs
        self.node_url = node_url.rstrip("/")

        try:
            private_key = PrivateKey.from_file(key_path)
            wallet = Wallet(private_key)
            self._client = self._build_weil_client(wallet)
        except Exception as exc:  # noqa: BLE001
            raise McpUnavailableError(f"Failed to initialize WeilClient: {exc}") from exc

    def _build_weil_client(self, wallet: Any) -> Any:
        try:
            return WeilClient(wallet=wallet, node_url=self.node_url)
        except TypeError:
            try:
                return WeilClient(wallet, self.node_url)
            except TypeError:
                return WeilClient(wallet)

    def is_available(self) -> bool:
        return bool(self._client and self._tool_specs)

    def discover_tools(self) -> Dict[str, ToolSpec]:
        return dict(self._tool_specs)

    def call_tool(
        self,
        *,
        tool_name: str,
        method_name: str,
        payload: Dict[str, Any],
        timeout_seconds: float,
        tool_spec: ToolSpec,
    ) -> Dict[str, Any]:
        del tool_name
        del timeout_seconds

        if not tool_spec.applet_id:
            raise ToolExecutionError("Missing applet_id in tool spec")

        execute_fn = getattr(self._client, "execute", None)
        if execute_fn is None:
            raise ToolExecutionError("WeilClient.execute is not available in installed SDK")

        response: Any
        signature_errors: list[Exception] = []
        call_patterns = (
            lambda: execute_fn(tool_spec.applet_id, method_name, payload),
            lambda: execute_fn(
                contract_id=tool_spec.applet_id,
                method=method_name,
                args=payload,
            ),
            lambda: execute_fn(tool_spec.applet_id, method_name, args=payload),
        )

        for call in call_patterns:
            try:
                response = call()
                break
            except TypeError as exc:
                signature_errors.append(exc)
        else:
            raise ToolExecutionError(
                "Unable to invoke WeilClient.execute with supported signatures: "
                + "; ".join(str(err) for err in signature_errors)
            )

        if inspect.isawaitable(response):
            try:
                response = asyncio.run(response)
            except RuntimeError as exc:
                raise ToolExecutionError(
                    "Async WeilClient.execute could not be resolved in current context"
                ) from exc

        if isinstance(response, dict):
            return response

        for attr in ("model_dump", "dict", "to_dict"):
            serializer = getattr(response, attr, None)
            if callable(serializer):
                serialized = serializer()
                if isinstance(serialized, dict):
                    return serialized
                return {"result": serialized}

        return {"result": response}


class WeilchainHybridMCPClient:
    """Try SDK first; fall back to HTTP if SDK execution fails."""

    def __init__(self, sdk_client: Optional[MCPClient], http_client: MCPClient) -> None:
        self.sdk_client = sdk_client
        self.http_client = http_client

    def is_available(self) -> bool:
        return bool(
            (self.sdk_client and self.sdk_client.is_available())
            or self.http_client.is_available()
        )

    def discover_tools(self) -> Dict[str, ToolSpec]:
        if self.sdk_client and self.sdk_client.is_available():
            try:
                return self.sdk_client.discover_tools()
            except Exception:
                pass
        return self.http_client.discover_tools()

    def call_tool(
        self,
        *,
        tool_name: str,
        method_name: str,
        payload: Dict[str, Any],
        timeout_seconds: float,
        tool_spec: ToolSpec,
    ) -> Dict[str, Any]:
        if self.sdk_client and self.sdk_client.is_available():
            try:
                return self.sdk_client.call_tool(
                    tool_name=tool_name,
                    method_name=method_name,
                    payload=payload,
                    timeout_seconds=timeout_seconds,
                    tool_spec=tool_spec,
                )
            except Exception as exc:
                logger.debug("SDK call failed (%s: %s); falling back to HTTP client", type(exc).__name__, exc)
        return self.http_client.call_tool(
            tool_name=tool_name,
            method_name=method_name,
            payload=payload,
            timeout_seconds=timeout_seconds,
            tool_spec=tool_spec,
        )


class ToolRouter:
    def __init__(
        self,
        settings: Settings,
        mcp_client: Optional[MCPClient] = None,
        weil_auth_headers: Optional[Dict[str, str]] = None,
    ) -> None:
        self.settings = settings
        self._weil_auth_headers = weil_auth_headers or {}
        self.tool_specs = {
            "clause_extractor": ToolSpec(
                applet_id=settings.clause_extractor_applet_id,
                interface="ClauseExtractor",
                default_method="extract_clauses",
            ),
            "risk_scorer": ToolSpec(
                applet_id=settings.risk_scorer_applet_id,
                interface="RiskScorer",
                default_method="score_clause_risk",
            ),
        }

        if mcp_client is not None:
            self.mcp_client = mcp_client
        else:
            self.mcp_client = self._build_real_mcp_client()

    def _build_real_mcp_client(self) -> MCPClient:
        """Build the best available MCP client.

        Priority: SDK → HTTP → LocalFallback.  Never raises — the agent
        must always be able to run (offline demo mode uses deterministic
        local parsing which mirrors the on-chain WASM applets).
        """
        required_env = {
            "WEILCHAIN_NODE_URL": self.settings.weilchain_node_url,
            "CLAUSE_EXTRACTOR_APPLET_ID": self.settings.clause_extractor_applet_id,
            "RISK_SCORER_APPLET_ID": self.settings.risk_scorer_applet_id,
            "WEILCHAIN_WALLET_PATH": self.settings.weilchain_wallet_path,
        }
        missing = sorted(key for key, value in required_env.items() if not value)
        if missing:
            logger.warning(
                "Missing Weilchain config (%s) — falling back to local MCP",
                ", ".join(missing),
            )
            return _get_local_fallback_class()(tool_specs=self.tool_specs)

        try:
            sdk_client: Optional[MCPClient] = None
            try:
                sdk_client = WeilchainSDKMCPClient(
                    node_url=self.settings.weilchain_node_url,
                    wallet_path=self.settings.weilchain_wallet_path,
                    tool_specs=self.tool_specs,
                )
            except Exception as exc:  # noqa: BLE001
                logger.info(
                    "Weilchain SDK unavailable (%s: %s); will try HTTP — "
                    "this is normal if applets aren't deployed yet",
                    type(exc).__name__, exc,
                )
                sdk_client = None

            http_client = WeilchainHTTPMCPClient(
                node_url=self.settings.weilchain_node_url,
                tool_specs=self.tool_specs,
                weil_auth_headers=self._weil_auth_headers,
            )

            client: MCPClient = WeilchainHybridMCPClient(sdk_client, http_client)

            discovered = client.discover_tools()
            required = {"clause_extractor", "risk_scorer"}
            missing_tools = sorted(required - set(discovered.keys()))
            if missing_tools:
                raise McpUnavailableError(
                    f"Required tools not discovered: {missing_tools}"
                )

            logger.info("MCP client ready (SDK=%s, HTTP=%s)", sdk_client is not None, True)
            return client
        except Exception as exc:  # noqa: BLE001
            logger.info(
                "Weilchain MCP not available (%s: %s) — using LocalFallback "
                "(correct for dev, applets not deployed yet)",
                type(exc).__name__, exc,
            )
            return _get_local_fallback_class()(tool_specs=self.tool_specs)

    def execute_tool(self, tool_name: str, payload: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        tool_spec = self.tool_specs.get(tool_name)
        if not tool_spec:
            raise ToolExecutionError(f"Unknown tool: {tool_name}")

        if not self.mcp_client.is_available():
            raise McpUnavailableError("MCP unavailable")

        discovered = self.mcp_client.discover_tools()
        if tool_name not in discovered:
            raise ToolExecutionError(f"Tool not discovered in MCP registry: {tool_name}")

        request_payload = dict(payload)
        method_name = request_payload.pop("_method", None)
        if method_name is None:
            method_name = tool_spec.default_method

        result = self._try_call(tool_name, str(method_name), request_payload, tool_spec)

        # If the primary MCP client failed and we aren't already using
        # LocalFallback, transparently retry with the deterministic local
        # implementation so the pipeline never returns empty results.
        if not result.success and not isinstance(self.mcp_client, _get_local_fallback_class()):
            logger.warning("⚠️ MCP failed — LocalFallback (tool: %s, error: %s)", tool_name, result.error)
            fallback = _get_local_fallback_class()(tool_specs=self.tool_specs)
            result = self._try_call(
                tool_name, str(method_name), request_payload, tool_spec,
                client_override=fallback,
            )

        return result

    def _try_call(
        self,
        tool_name: str,
        method_name: str,
        payload: Dict[str, Any],
        tool_spec: ToolSpec,
        client_override: Optional[MCPClient] = None,
    ) -> ToolResult:
        client = client_override or self.mcp_client
        last_error: Optional[str] = None
        for attempt in range(1, self.settings.max_retries + 2):
            started = time.time()
            try:
                envelope = client.call_tool(
                    tool_name=tool_name,
                    method_name=str(method_name),
                    payload=payload,
                    timeout_seconds=self.settings.mcp_timeout_seconds,
                    tool_spec=tool_spec,
                )
                latency_ms = int((time.time() - started) * 1000)
                data = _normalize_envelope(envelope)
                # Log success for real Weilchain MCP calls (not LocalFallback)
                if not isinstance(client, _get_local_fallback_class()):
                    logger.info("🔗 Real Weilchain MCP: %s", tool_spec.applet_id)
                return ToolResult(
                    success=True,
                    data=data,
                    error=None,
                    attempts=attempt,
                    latency_ms=latency_ms,
                    raw=envelope,
                )
            except McpUnavailableError:
                raise
            except Exception as exc:  # noqa: BLE001
                latency_ms = int((time.time() - started) * 1000)
                last_error = str(exc)
                if attempt <= self.settings.max_retries:
                    time.sleep(self.settings.retry_backoff_seconds * attempt)
                    continue
                return ToolResult(
                    success=False,
                    data=None,
                    error=last_error,
                    attempts=attempt,
                    latency_ms=latency_ms,
                    raw=None,
                )

        return ToolResult(False, None, last_error or "Unknown tool error", self.settings.max_retries + 1, 0, None)


def _normalize_envelope(envelope: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(envelope, dict):
        raise ToolExecutionError("Invalid MCP response envelope")
    if "ok" in envelope and not envelope["ok"]:
        message = envelope.get("error", "tool call failed")
        raise ToolExecutionError(str(message))

    if "result" in envelope:
        return _normalize_result_value(envelope["result"])
    if "data" in envelope:
        return {"payload": envelope["data"]} if not isinstance(envelope["data"], dict) else envelope["data"]
    if "value" in envelope:
        return {"payload": envelope["value"]} if not isinstance(envelope["value"], dict) else envelope["value"]
    return envelope


def _normalize_result_value(result: Any) -> Dict[str, Any]:
    if isinstance(result, dict):
        if "Err" in result:
            raise ToolExecutionError(str(result["Err"]))
        if "Ok" in result:
            ok_value = result["Ok"]
            return {"payload": ok_value} if not isinstance(ok_value, dict) else ok_value
        if "ok" in result and result.get("ok") is False:
            raise ToolExecutionError(str(result.get("error", "tool call failed")))
        if "ok" in result and result.get("ok") is True:
            value = result.get("value", result.get("data"))
            if value is None:
                return {}
            return {"payload": value} if not isinstance(value, dict) else value
        return result
    return {"payload": result}


DEFAULT_ROUTER: Optional[ToolRouter] = None


def set_default_router(router: ToolRouter) -> None:
    global DEFAULT_ROUTER
    DEFAULT_ROUTER = router


def execute_tool(tool_name: str, payload: Dict[str, Any], ctx: ToolContext) -> ToolResult:
    if DEFAULT_ROUTER is None:
        raise ToolExecutionError("Default tool router not configured")
    return DEFAULT_ROUTER.execute_tool(tool_name, payload, ctx)
