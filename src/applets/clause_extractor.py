from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from src.types import Clause, ToolContext


class ClauseParseError(ValueError):
    pass


# ── LLM client helpers ────────────────────────────────────────────────────

def _make_llm_client(ctx: ToolContext) -> Any:
    """Return a (kind, client) tuple.  Priority: Groq > Gemini > OpenAI > Anthropic.

    Groq provides blazing-fast inference on Llama 3.3 70B with a generous
    free tier.  Set USE_GROQ=true + GROQ_API_KEY in .env.
    """
    # 1) Groq (fastest — highest priority)
    use_groq = getattr(ctx, "use_groq", False) or os.getenv("USE_GROQ", "").lower() in {"1", "true", "yes"}
    if use_groq:
        groq_key = os.getenv("GROQ_API_KEY", "")
        if groq_key:
            try:
                from groq import Groq  # type: ignore
                model_name = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
                return ("groq", (Groq(api_key=groq_key), model_name))
            except Exception:  # noqa: BLE001
                pass  # fall through

    # 2) Gemini (free tier)
    use_gemini = getattr(ctx, "use_gemini", False) or os.getenv("USE_GEMINI", "").lower() in {"1", "true", "yes"}
    if use_gemini:
        gemini_key = os.getenv("GEMINI_API_KEY", "")
        if gemini_key:
            try:
                from google import genai  # type: ignore
                client = genai.Client(api_key=gemini_key)
                model_name = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
                return ("gemini", (client, model_name))
            except Exception:  # noqa: BLE001
                pass  # fall through

    # 3) OpenAI
    use_openai = getattr(ctx, "use_openai", False) or os.getenv("USE_OPENAI", "").lower() in {"1", "true", "yes"}
    if use_openai:
        try:
            from openai import OpenAI  # type: ignore
            return ("openai", OpenAI(api_key=os.getenv("OPENAI_API_KEY")))
        except Exception:  # noqa: BLE001
            pass  # fall through

    # 4) Anthropic (fallback)
    from anthropic import Anthropic  # type: ignore
    return ("anthropic", Anthropic())


def _call_llm(client_tuple: Any, model: str, prompt: str, max_tokens: int) -> str:
    """Call the LLM and return the raw text response."""
    kind, client = client_tuple

    if kind == "groq":
        groq_client, groq_model = client
        response = groq_client.chat.completions.create(
            model=groq_model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        content = response.choices[0].message.content
        if not content:
            raise ClauseParseError("Empty Groq response")
        return content

    if kind == "gemini":
        gemini_client, gemini_model = client
        response = gemini_client.models.generate_content(
            model=gemini_model,
            contents=prompt,
        )
        text = response.text
        if not text:
            raise ClauseParseError("Empty Gemini response")
        return text

    if kind == "openai":
        openai_model = os.getenv("OPENAI_MODEL", model if "gpt" in model else "gpt-4o")
        response = client.chat.completions.create(
            model=openai_model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        content = response.choices[0].message.content
        if not content:
            raise ClauseParseError("Empty OpenAI response")
        return content

    # Anthropic
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    if not response.content:
        raise ClauseParseError("Empty Anthropic response")
    return response.content[0].text


def _strip_fenced_json(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        parts = text.split("```")
        if len(parts) >= 2:
            text = parts[1].strip()
        if text.startswith("json"):
            text = text[4:].strip()
    return text


def parse_clauses_response(raw: Any) -> List[Clause]:
    payload = raw
    if isinstance(payload, str):
        try:
            payload = json.loads(_strip_fenced_json(payload))
        except json.JSONDecodeError as exc:
            raise ClauseParseError("Clause response is not valid JSON") from exc

    if not isinstance(payload, list):
        raise ClauseParseError("Clause response must be a JSON list")

    clauses: List[Clause] = []
    for idx, item in enumerate(payload, start=1):
        if not isinstance(item, dict):
            raise ClauseParseError(f"Clause #{idx} must be an object")

        clause_id = item.get("id")
        title = item.get("title")
        text = item.get("text")

        if not isinstance(clause_id, int):
            raise ClauseParseError(f"Clause #{idx} id must be u32 integer")
        if clause_id < 0 or clause_id > 2**32 - 1:
            raise ClauseParseError(f"Clause #{idx} id is out of u32 range")
        if not isinstance(title, str) or not title.strip():
            raise ClauseParseError(f"Clause #{idx} title must be a non-empty string")
        if not isinstance(text, str) or not text.strip():
            raise ClauseParseError(f"Clause #{idx} text must be a non-empty string")

        clauses.append(Clause(id=clause_id, title=title.strip(), text=text.strip()))

    return clauses


def _extract_payload(raw_payload: Any) -> Any:
    if isinstance(raw_payload, dict):
        if "clauses" in raw_payload:
            return raw_payload["clauses"]
        if "payload" in raw_payload:
            return raw_payload["payload"]
        if "result" in raw_payload:
            result = raw_payload["result"]
            if isinstance(result, dict):
                if "Ok" in result:
                    return result["Ok"]
                if "Err" in result:
                    raise ClauseParseError(str(result["Err"]))
            return result
    return raw_payload


def extract_clauses(contract_text: str, ctx: ToolContext, client: Optional[Any] = None) -> List[Clause]:
    if not contract_text.strip():
        raise ClauseParseError("contract_text cannot be empty")

    llm = client or _make_llm_client(ctx)
    prompt = (
        "Extract all distinct clauses from this legal contract. Return JSON array only with"
        " fields id,title,text.\n\nContract:\n"
        + contract_text[:12000]
    )
    raw = _call_llm(llm, ctx.model, prompt, max_tokens=2048)
    return parse_clauses_response(raw)


def extract_clauses_from_payload(payload: Dict[str, Any]) -> List[Clause]:
    return parse_clauses_response(_extract_payload(payload))
