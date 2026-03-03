from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from anthropic import Anthropic

from src.types import Clause, RiskLevel, RiskScore, ToolContext


VALID_LEVELS = {RiskLevel.LOW.value, RiskLevel.MEDIUM.value, RiskLevel.HIGH.value}


class RiskParseError(ValueError):
    pass


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
    if not isinstance(confidence_raw, str):
        raise RiskParseError("confidence must be a string (WIDL schema)")
    try:
        confidence = float(confidence_raw)
    except ValueError as exc:
        raise RiskParseError("confidence string must be numeric") from exc
    if confidence < 0 or confidence > 1:
        raise RiskParseError("confidence must be between 0 and 1")

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


def score_clause_risk(clause: Clause, ctx: ToolContext, client: Optional[Anthropic] = None) -> RiskScore:
    llm = client or Anthropic()
    response = llm.messages.create(
        model=ctx.model,
        max_tokens=512,
        messages=[
            {
                "role": "user",
                "content": (
                    "Analyze this legal clause for risk and return JSON only with risk_level,"
                    " confidence (string), reason, flags where each flag has code and description."
                    " The reason must be ONE specific sentence tied directly to this clause text,"
                    " explaining exactly why it is risky (e.g., '10-year worldwide non-compete far"
                    " exceeds enforceable limits in most jurisdictions'). Avoid generic reasons such"
                    " as 'Contains unusually restrictive or unbounded terms'."
                    "\\n\\nClause:\\n"
                    + clause.text[:3000]
                ),
            }
        ],
    )

    if not response.content:
        raise RiskParseError("Empty LLM response")

    return parse_risk_response(response.content[0].text, clause)


def score_clause_from_payload(payload: Dict[str, Any], clause: Clause) -> RiskScore:
    return parse_risk_response(_extract_payload(payload), clause)
