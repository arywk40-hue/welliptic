from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from src.types import Clause, RiskLevel, RiskScore, ToolContext


VALID_LEVELS = {RiskLevel.LOW.value, RiskLevel.MEDIUM.value, RiskLevel.HIGH.value}


class RiskParseError(ValueError):
    pass


# ── LLM client helpers ────────────────────────────────────────────────────

def _make_llm_client(ctx: ToolContext) -> Any:
    """Return a (kind, client) tuple.  Priority: Groq > Gemini > OpenAI > Anthropic."""
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
            raise RiskParseError("Empty Groq response")
        return content

    if kind == "gemini":
        gemini_client, gemini_model = client
        response = gemini_client.models.generate_content(
            model=gemini_model,
            contents=prompt,
        )
        text = response.text
        if not text:
            raise RiskParseError("Empty Gemini response")
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
            raise RiskParseError("Empty OpenAI response")
        return content

    # Anthropic
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    if not response.content:
        raise RiskParseError("Empty Anthropic response")
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


def _parse_risk_flags(flags: Any) -> List[str]:
    if not isinstance(flags, list):
        raise RiskParseError("flags must be a list<RiskFlag>")

    parsed: List[str] = []
    for idx, item in enumerate(flags, start=1):
        if not isinstance(item, dict):
            raise RiskParseError(f"flags[{idx}] must be an object with code + description")
        code = item.get("code")
        description = item.get("description")
        if not isinstance(code, str) or not code.strip():
            raise RiskParseError(f"flags[{idx}].code must be a non-empty string")
        if not isinstance(description, str) or not description.strip():
            raise RiskParseError(f"flags[{idx}].description must be a non-empty string")
        parsed.append(f"{code.strip()}: {description.strip()}")
    return parsed


def parse_risk_response(raw: Any, clause: Clause) -> RiskScore:
    payload = raw
    if isinstance(payload, str):
        try:
            payload = json.loads(_strip_fenced_json(payload))
        except json.JSONDecodeError as exc:
            raise RiskParseError("Risk response is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise RiskParseError("Risk scorer output must be a JSON object")

    level = payload.get("risk_level")
    if not isinstance(level, str):
        raise RiskParseError("risk_level must be a string")
    level = level.upper()
    if level not in VALID_LEVELS:
        raise RiskParseError(f"Invalid risk level: {level}")

    confidence_raw = payload.get("confidence")
    # Some LLMs return confidence as a number, word ("high"), or string "0.85".
    # Normalize all forms into a float between 0 and 1.
    if isinstance(confidence_raw, (int, float)):
        confidence = float(confidence_raw)
        # If the model returned e.g. 85 instead of 0.85, normalize
        if confidence > 1:
            confidence = confidence / 100.0
    elif isinstance(confidence_raw, str):
        # Try numeric parse first
        try:
            confidence = float(confidence_raw.strip().rstrip("%"))
            if confidence > 1:
                confidence = confidence / 100.0
        except ValueError:
            # Word-based: "high" → 0.9, "medium" → 0.6, "low" → 0.3
            word_map = {"high": 0.9, "medium": 0.6, "moderate": 0.6, "low": 0.3, "very high": 0.95, "very low": 0.15}
            confidence = word_map.get(confidence_raw.strip().lower(), 0.5)
    else:
        confidence = 0.5  # fallback
    confidence = max(0.0, min(1.0, confidence))

    reason = payload.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        raise RiskParseError("reason is required and must be a non-empty string")

    flags = _parse_risk_flags(payload.get("flags", []))

    return RiskScore(
        clause_id=clause.id,
        clause_title=clause.title,
        risk_level=RiskLevel(level),
        confidence=confidence,
        reason=reason.strip(),
        flags=flags,
    )


def _extract_payload(raw_payload: Any) -> Any:
    if isinstance(raw_payload, dict):
        if "risk" in raw_payload:
            return raw_payload["risk"]
        if "payload" in raw_payload:
            return raw_payload["payload"]
        if "result" in raw_payload:
            result = raw_payload["result"]
            if isinstance(result, dict):
                if "Ok" in result:
                    return result["Ok"]
                if "Err" in result:
                    raise RiskParseError(str(result["Err"]))
            return result
    return raw_payload


def score_clause_risk(clause: Clause, ctx: ToolContext, client: Optional[Any] = None) -> RiskScore:
    llm = client or _make_llm_client(ctx)
    prompt = (
        "Analyze this legal clause for risk. Return ONLY a JSON object (no markdown, no"
        " explanation) with these exact fields:\n"
        '  "risk_level": "HIGH" or "MEDIUM" or "LOW",\n'
        '  "confidence": "0.85" (a decimal string between 0 and 1),\n'
        '  "reason": "One specific sentence explaining the risk",\n'
        '  "flags": [{"code": "FLAG_CODE", "description": "explanation"}]\n\n'
        "The reason must be ONE specific sentence tied directly to this clause text,"
        " explaining exactly why it is risky. Avoid generic reasons.\n\n"
        "Clause:\n"
        + clause.text[:3000]
    )
    raw = _call_llm(llm, ctx.model, prompt, max_tokens=512)
    return parse_risk_response(raw, clause)


def score_clause_from_payload(payload: Dict[str, Any], clause: Clause) -> RiskScore:
    return parse_risk_response(_extract_payload(payload), clause)
