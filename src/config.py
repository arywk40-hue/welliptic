from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Settings:
    anthropic_api_key: str
    anthropic_model: str = "claude-opus-4-1"
    max_retries: int = 2
    retry_backoff_seconds: float = 0.3
    runs_dir: Path = Path(".runs")
    mcp_endpoint: str = ""
    weilchain_node_url: str = ""
    clause_extractor_applet_id: str = ""
    risk_scorer_applet_id: str = ""
    weilchain_wallet_path: str = "private_key.wc"
    mcp_timeout_seconds: float = 20.0
    enforce_mcp: bool = True


def load_settings() -> Settings:
    return Settings(
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", ""),
        anthropic_model=os.getenv("ANTHROPIC_MODEL", "claude-opus-4-1"),
        max_retries=int(os.getenv("LEXAUDIT_MAX_RETRIES", "2")),
        retry_backoff_seconds=float(os.getenv("LEXAUDIT_RETRY_BACKOFF", "0.3")),
        runs_dir=Path(os.getenv("LEXAUDIT_RUNS_DIR", ".runs")),
        mcp_endpoint=os.getenv("WEILCHAIN_MCP_ENDPOINT", ""),
        weilchain_node_url=os.getenv("WEILCHAIN_NODE_URL", "").strip(),
        clause_extractor_applet_id=os.getenv("CLAUSE_EXTRACTOR_APPLET_ID", "").strip(),
        risk_scorer_applet_id=os.getenv("RISK_SCORER_APPLET_ID", "").strip(),
        weilchain_wallet_path=os.getenv("WEILCHAIN_WALLET_PATH", "private_key.wc").strip(),
        mcp_timeout_seconds=float(os.getenv("WEILCHAIN_MCP_TIMEOUT", "20.0")),
        enforce_mcp=os.getenv("LEXAUDIT_ENFORCE_MCP", "true").lower() in {"1", "true", "yes"},
    )
