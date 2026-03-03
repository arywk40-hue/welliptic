from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from anthropic import Anthropic

from src.types import Clause, ToolContext


class ClauseParseError(ValueError):
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


def extract_clauses(contract_text: str, ctx: ToolContext, client: Optional[Anthropic] = None) -> List[Clause]:
    if not contract_text.strip():
        raise ClauseParseError("contract_text cannot be empty")

    llm = client or Anthropic()
    response = llm.messages.create(
        model=ctx.model,
        max_tokens=2048,
        messages=[
            {
                "role": "user",
                "content": (
                    "Extract all distinct clauses from this legal contract. Return JSON array only with"
                    " fields id,title,text.\\n\\nContract:\\n"
                    + contract_text[:12000]
                ),
            }
        ],
    )

    if not response.content:
        raise ClauseParseError("Empty LLM response")

    raw = response.content[0].text
    return parse_clauses_response(raw)


def extract_clauses_from_payload(payload: Dict[str, Any]) -> List[Clause]:
    return parse_clauses_response(_extract_payload(payload))
