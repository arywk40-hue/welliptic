from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Settings:
    anthropic_api_key: str
    openai_api_key: str = ""
    gemini_api_key: str = ""
    groq_api_key: str = ""
    # Model config — priority: Groq > Gemini > OpenAI > Anthropic
    anthropic_model: str = "claude-opus-4-1"
    openai_model: str = "gpt-4o"
    gemini_model: str = "gemini-2.0-flash"
    groq_model: str = "llama-3.3-70b-versatile"
    use_openai: bool = False
    use_gemini: bool = False
    use_groq: bool = False  # Set USE_GROQ=true in .env (highest priority)
    max_retries: int = 2
    retry_backoff_seconds: float = 0.3
    runs_dir: Path = Path(".runs")
    mcp_endpoint: str = ""
    weilchain_node_url: str = "https://sentinel.weilliptic.ai"
    weilchain_pod_url: str = "https://marauder.weilliptic.ai"
    clause_extractor_applet_id: str = ""
    risk_scorer_applet_id: str = ""
    weilchain_wallet_path: str = "private_key.wc"
    mcp_timeout_seconds: float = 20.0
    enforce_mcp: bool = True
    disable_weil_sdk: bool = False


def load_settings() -> Settings:
    disable_sdk_env = os.getenv("DISABLE_WEIL_SDK", "").lower() in {"1", "true", "yes"}
    disable_sdk_pytest = "PYTEST_CURRENT_TEST" in os.environ
    return Settings(
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", ""),
        openai_api_key=os.getenv("OPENAI_API_KEY", ""),
        gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
        groq_api_key=os.getenv("GROQ_API_KEY", ""),
        anthropic_model=os.getenv("ANTHROPIC_MODEL", "claude-opus-4-1"),
        openai_model=os.getenv("OPENAI_MODEL", "gpt-4o"),
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-2.0-flash"),
        groq_model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
        use_openai=os.getenv("USE_OPENAI", "false").lower() in {"1", "true", "yes"},
        use_gemini=os.getenv("USE_GEMINI", "false").lower() in {"1", "true", "yes"},
        use_groq=os.getenv("USE_GROQ", "false").lower() in {"1", "true", "yes"},
        max_retries=int(os.getenv("LEXAUDIT_MAX_RETRIES", "2")),
        retry_backoff_seconds=float(os.getenv("LEXAUDIT_RETRY_BACKOFF", "0.3")),
        runs_dir=Path(os.getenv("LEXAUDIT_RUNS_DIR", ".runs")),
        mcp_endpoint=os.getenv("WEILCHAIN_MCP_ENDPOINT", ""),
        weilchain_node_url=os.getenv("WEILCHAIN_NODE_URL", "https://sentinel.weilliptic.ai").strip(),
        weilchain_pod_url=os.getenv("WEILCHAIN_POD_URL", "https://marauder.weilliptic.ai").strip(),
        clause_extractor_applet_id=os.getenv("CLAUSE_EXTRACTOR_APPLET_ID", "").strip(),
        risk_scorer_applet_id=os.getenv("RISK_SCORER_APPLET_ID", "").strip(),
        weilchain_wallet_path=os.getenv("WEILCHAIN_WALLET_PATH", "private_key.wc").strip(),
        mcp_timeout_seconds=float(os.getenv("WEILCHAIN_MCP_TIMEOUT", "20.0")),
        enforce_mcp=os.getenv("LEXAUDIT_ENFORCE_MCP", "true").lower() in {"1", "true", "yes"},
        disable_weil_sdk=disable_sdk_env or disable_sdk_pytest,
    )
