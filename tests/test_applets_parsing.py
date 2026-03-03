from __future__ import annotations

import pytest

from src.applets.clause_extractor import extract_clauses_from_payload
from src.applets.risk_scorer import score_clause_from_payload
from src.types import Clause


def test_clause_parser_handles_fenced_json() -> None:
    payload = {
        "clauses": """```json
        [{"id":1,"title":"Payment","text":"Payment text"}]
        ```"""
    }
    clauses = extract_clauses_from_payload(payload)
    assert len(clauses) == 1
    assert clauses[0].title == "Payment"


def test_risk_parser_rejects_invalid_enum() -> None:
    clause = Clause(id=1, title="X", text="Y")
    payload = {"risk": {"risk_level": "CRITICAL", "confidence": "0.5", "reason": "bad", "flags": []}}
    with pytest.raises(ValueError):
        score_clause_from_payload(payload, clause)
