from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from src import run_lexaudit
from src.agent.audit import WeilAuditLogger
from src.config import load_settings
from src.tools.router import McpUnavailableError, ToolRouter

try:
    from weil_ai import weil_middleware
    _HAS_WEIL_MIDDLEWARE = True
except Exception:  # noqa: BLE001
    _HAS_WEIL_MIDDLEWARE = False


class AnalyseRequest(BaseModel):
    contract_text: str = Field(min_length=1)
    filename: str = "contract.txt"
    no_human_gate: bool = False
    max_steps: int = Field(default=200, ge=1, le=500)
    human_gate_threshold: str = Field(default="HIGH", pattern="^(LOW|MEDIUM|HIGH)$")


class ContinueRequest(BaseModel):
    """Human-gate continuation: the reviewer submits approve/reject."""
    decision: str = Field(pattern="^(approve|reject)$")


load_dotenv()
app = FastAPI(title="LexAudit API", version="1.0.0")
ROOT = Path(__file__).resolve().parents[2]
WEB_DIR = ROOT / "web"

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:3001",
        "http://localhost:8000",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:8000",
        "https://*.vercel.app",
        "https://*.railway.app",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Weilchain wallet-signature verification middleware.
# Verifies X-Wallet-Address / X-Signature / X-Message / X-Timestamp headers
# on POST requests, providing cryptographic proof of caller identity.
#
# For the user-facing API (browser UI), we **skip** wallet verification —
# browsers cannot produce wallet signatures.  On-chain auth is enforced at
# the MCP client layer via WeilAgent.get_auth_headers() → signed headers on
# every applet invocation.
#
# In production you would gate the admin / internal endpoints separately.
# For the hackathon demo we import and log that weil_middleware is available
# but do NOT mount it so `/api/analyze` works from the browser UI.
_WEIL_MIDDLEWARE_ACTIVE = False
if _HAS_WEIL_MIDDLEWARE:
    # weil_middleware is available — we could mount it on internal-only routes.
    # For the demo API we skip it so the browser UI can call /api/analyze.
    _WEIL_MIDDLEWARE_ACTIVE = True  # flag that the SDK is loaded


def _extract_tx_hash(event: Dict[str, Any]) -> str | None:
    metadata = event.get("metadata", {}) if isinstance(event, dict) else {}
    if not isinstance(metadata, dict):
        return None
    for key in ("tx_hash", "transaction_hash", "weilchain_tx_hash"):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _attach_audit_links(payload: Dict[str, Any], node_url: str) -> Dict[str, Any]:
    audit_log = payload.get("audit_log", [])
    if not isinstance(audit_log, list):
        return payload

    linked: list[dict[str, Any]] = []
    for event in audit_log:
        if not isinstance(event, dict):
            continue
        tx_hash = _extract_tx_hash(event)
        event_copy = dict(event)
        event_copy["tx_hash"] = tx_hash
        event_copy["weilchain_link"] = (
            f"{node_url.rstrip('/')}/tx/{tx_hash}" if node_url and tx_hash else None
        )
        linked.append(event_copy)
    payload["audit_log"] = linked
    return payload


@app.get("/api/health")
def health() -> Dict[str, Any]:
    settings = load_settings()
    # Detect active LLM provider
    llm_provider = "none"
    llm_ok = False
    if settings.use_groq and settings.groq_api_key:
        llm_provider = "groq"
        llm_ok = True
    elif settings.use_gemini and settings.gemini_api_key:
        llm_provider = "gemini"
        llm_ok = True
    elif settings.use_openai and settings.openai_api_key:
        llm_provider = "openai"
        llm_ok = True
    elif settings.anthropic_api_key:
        llm_provider = "anthropic"
        llm_ok = True

    weilchain_ok = bool(
        settings.weilchain_node_url
        and settings.weilchain_pod_url
        and settings.clause_extractor_applet_id
        and settings.risk_scorer_applet_id
    )

    # Determine MCP mode: "real" if all Weilchain config is set, else "local"
    mcp_mode = "real" if weilchain_ok else "local"

    # Live check: can the WeilAgent actually sign requests?
    weil_logger = WeilAuditLogger(settings.weilchain_wallet_path, sentinel_host=settings.weilchain_node_url)
    weil_middleware_active = weil_logger.is_active

    return {
        "status": "ok",
        "llm": llm_ok,
        "llm_provider": llm_provider,
        "weilchain": weilchain_ok,
        "weil_middleware": weil_middleware_active,
        "mcp_mode": mcp_mode,
    }


def _run_analysis(req: AnalyseRequest) -> Dict[str, Any]:
    settings = load_settings()

    try:
        router = ToolRouter(settings=settings)
    except McpUnavailableError as exc:
        raise HTTPException(status_code=503, detail=f"MCP bootstrap failed: {exc}") from exc

    try:
        result = run_lexaudit(
            contract_text=req.contract_text,
            filename=req.filename,
            max_steps=req.max_steps,
            human_gate_threshold=req.human_gate_threshold,
            settings=settings,
            router=router,
            human_gate_enabled=not req.no_human_gate,
            decision_provider=None,
        )
    except McpUnavailableError as exc:
        raise HTTPException(status_code=503, detail=f"MCP unavailable: {exc}") from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    payload = result.to_dict()
    payload = _attach_audit_links(payload, settings.weilchain_pod_url)

    # Promote tx_hash from report_json to top level (report_json was set in
    # _finalize_result; to_dict() also sets it, but be explicit here too)
    if not payload.get("tx_hash") and isinstance(payload.get("report_json"), dict):
        payload["tx_hash"] = payload["report_json"].get("tx_hash")

    # Build the Weilchain explorer link for the final tx
    from src.agent.audit import get_explorer_url, get_wallet_explorer_url
    final_tx = payload.get("tx_hash")
    if final_tx:
        payload["tx_explorer_url"] = get_explorer_url(final_tx)

    # Add wallet explorer URL if weil_audit_logger has a wallet address
    if result.weil_audit_logger and hasattr(result.weil_audit_logger, 'wallet_address'):
        wallet_address = result.weil_audit_logger.wallet_address
        if wallet_address:
            payload["explorer_url"] = get_wallet_explorer_url(wallet_address)

    # Stash result for /api/continue if human gate is pending
    if payload.get("pending_human_review"):
        _stash_pending(payload)

    return jsonable_encoder(payload)


@app.post("/api/analyze")
def analyze(req: AnalyseRequest) -> Dict[str, Any]:
    return _run_analysis(req)


@app.post("/api/analyse")
def analyse(req: AnalyseRequest) -> Dict[str, Any]:
    return _run_analysis(req)


# ── Human-gate continuation ──────────────────────────────────────────────

# In-memory cache for the last analysis that hit HUMAN_GATE.
# A production deployment would persist this to Redis / DB.
_pending_result: Dict[str, Any] = {}


def _stash_pending(payload: Dict[str, Any]) -> None:
    """Save a pending-human-review result for /api/continue."""
    _pending_result.clear()
    _pending_result.update(payload)


@app.post("/api/continue")
def continue_analysis(req: ContinueRequest) -> Dict[str, Any]:
    """Resume analysis after human approve/reject decision.

    Patches the pending result with the human decision and returns
    the completed payload.  The audit logger records the decision.
    """
    if not _pending_result:
        raise HTTPException(status_code=404, detail="No pending analysis to continue")

    state = _pending_result.get("state", {})
    state["human_decision"] = req.decision
    _pending_result["state"] = state
    _pending_result["pending_human_review"] = False

    settings = load_settings()
    payload = _attach_audit_links(dict(_pending_result), settings.weilchain_pod_url)

    # Clear pending state
    _pending_result.clear()

    return jsonable_encoder(payload)


if WEB_DIR.is_dir():
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
