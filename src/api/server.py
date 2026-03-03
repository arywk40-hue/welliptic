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
    no_human_gate: bool = True
    max_steps: int = Field(default=50, ge=1, le=500)
    human_gate_threshold: str = Field(default="HIGH", pattern="^(LOW|MEDIUM|HIGH)$")


class ReviewDecisionRequest(BaseModel):
    session_id: str
    decision: str = Field(pattern="^(approve|reject)$")


load_dotenv()
app = FastAPI(title="LexAudit API", version="1.0.0")
ROOT = Path(__file__).resolve().parents[2]
WEB_DIR = ROOT / "web"

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Weilchain wallet-signature verification middleware.
# Verifies X-Wallet-Address / X-Signature / X-Message / X-Timestamp headers
# on POST requests, providing cryptographic proof of caller identity.
#
# For the user-facing API (browser UI), we register middleware but skip
# verification on /api/* paths (the browser cannot produce wallet signatures).
# The on-chain auth is enforced at the MCP client layer via
# WeilAgent.get_auth_headers() → signed headers on every applet invocation.
#
# This demonstrates full weil_middleware() integration per the SDK pattern:
#   app.add_middleware(weil_middleware())
_WEIL_MIDDLEWARE_ACTIVE = False
if _HAS_WEIL_MIDDLEWARE:
    try:
        app.add_middleware(weil_middleware())
        _WEIL_MIDDLEWARE_ACTIVE = True
    except Exception:  # noqa: BLE001
        pass

# In-memory pending session store.
# Maps session_id → original request data for sessions pending human review.
# Replace with Redis/DB for multi-process or persistent deployments.
_pending_sessions: Dict[str, Any] = {}


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
    claude_ok = bool(settings.anthropic_api_key)
    weilchain_ok = bool(
        settings.weilchain_node_url
        and settings.clause_extractor_applet_id
        and settings.risk_scorer_applet_id
    )
    return {
        "status": "ok",
        "claude": claude_ok,
        "weilchain": weilchain_ok,
        "weil_middleware": _WEIL_MIDDLEWARE_ACTIVE,
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

    # Store pending sessions so /api/review-decision can resume them.
    if result.pending_human_review and result.session_id:
        _pending_sessions[result.session_id] = {
            "contract_text": req.contract_text,
            "filename": req.filename,
            "human_gate_threshold": req.human_gate_threshold,
            "max_steps": req.max_steps,
        }

    payload = result.to_dict()
    payload = _attach_audit_links(payload, settings.weilchain_node_url)
    return jsonable_encoder(payload)


@app.post("/api/analyze")
def analyze(req: AnalyseRequest) -> Dict[str, Any]:
    return _run_analysis(req)


@app.post("/api/analyse")
def analyse(req: AnalyseRequest) -> Dict[str, Any]:
    return _run_analysis(req)


@app.post("/api/review-decision")
def review_decision(req: ReviewDecisionRequest) -> Dict[str, Any]:
    """Resume a pending human-gate session with an approve/reject decision.

    The UI calls this after /api/analyze returns pending_human_review: true.
    """
    if req.session_id not in _pending_sessions:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Session '{req.session_id}' not found or already resolved. "
                "Re-submit the contract via /api/analyze to start a new session."
            ),
        )

    pending = _pending_sessions.pop(req.session_id)
    contract_text = pending.get("contract_text", "")
    filename = pending.get("filename", "contract.txt")
    human_gate_threshold = pending.get("human_gate_threshold", "HIGH")
    max_steps = pending.get("max_steps", 50)
    decision_value = req.decision

    settings = load_settings()

    try:
        router = ToolRouter(settings=settings)
    except McpUnavailableError as exc:
        raise HTTPException(status_code=503, detail=f"MCP bootstrap failed: {exc}") from exc

    try:
        result = run_lexaudit(
            contract_text=contract_text,
            filename=filename,
            max_steps=max_steps,
            human_gate_threshold=human_gate_threshold,
            settings=settings,
            router=router,
            human_gate_enabled=True,
            decision_provider=lambda _risks: decision_value,
        )
    except McpUnavailableError as exc:
        raise HTTPException(status_code=503, detail=f"MCP unavailable: {exc}") from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    payload = result.to_dict()
    payload = _attach_audit_links(payload, settings.weilchain_node_url)
    return jsonable_encoder(payload)


if WEB_DIR.is_dir():
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
