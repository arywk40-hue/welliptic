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


def test_risk_parser_accepts_all_valid_levels() -> None:
    """Test that all valid risk levels (LOW, MEDIUM, HIGH) parse correctly."""
    clause = Clause(id=1, title="Test", text="Text")

    for level in ["LOW", "MEDIUM", "HIGH"]:
        payload = {
            "risk": {
                "risk_level": level,
                "confidence": "0.8",
                "reason": "Test reason",
                "flags": [{"code": "TEST", "description": "Test flag"}],
            }
        }
        result = score_clause_from_payload(payload, clause)
        assert result.risk_level.value == level
        assert isinstance(result.confidence, float)
        assert len(result.flags) == 1
        assert result.flags[0] == "TEST: Test flag"


def test_clause_parser_handles_empty_contract() -> None:
    """Empty contract array should not crash."""
    # Empty array is valid JSON - should return empty list
    payload = {"clauses": "[]"}
    clauses = extract_clauses_from_payload(payload)
    # Empty array is valid, returns 0 clauses
    assert len(clauses) == 0

    # Fallback: provide a minimal valid clause with text
    payload2 = {"clauses": '[{"id": 1, "title": "Minimal", "text": "Minimal clause text"}]'}
    clauses2 = extract_clauses_from_payload(payload2)
    assert len(clauses2) == 1
