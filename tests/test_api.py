from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.api.server import app, _pending_sessions
from src.tools.router import ToolRouter
from tests.conftest import InMemoryMCPClient


@pytest.fixture(autouse=True)
def clear_pending():
    """Clear the pending sessions dict before each test."""
    _pending_sessions.clear()
    yield
    _pending_sessions.clear()


def test_health_endpoint():
    client = TestClient(app)
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "claude" in data
    assert "weilchain" in data


def test_review_decision_404_when_no_pending_session():
    client = TestClient(app)
    response = client.post(
        "/api/review-decision",
        json={"session_id": "nonexistent-session-id", "decision": "approve"},
    )
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_review_decision_invalid_decision():
    client = TestClient(app)
    response = client.post(
        "/api/review-decision",
        json={"session_id": "some-id", "decision": "maybe"},
    )
    # Pydantic validation should reject "maybe"
    assert response.status_code == 422


def test_pending_session_stored_on_analyze(monkeypatch):
    """When analyze returns pending_human_review, session is stored."""
    def clause_extractor(payload: dict) -> dict:
        return {"clauses": [{"id": 1, "title": "Non-compete", "text": "worldwide irrevocable perpetual"}]}

    def risk_scorer(payload: dict) -> dict:
        return {
            "risk": {
                "risk_level": "HIGH",
                "confidence": "0.9",
                "reason": "Overly broad worldwide restriction",
                "flags": [{"code": "WORLDWIDE_SCOPE", "description": "Contains 'worldwide'"}],
            }
        }

    from src.config import Settings

    def mock_router(settings):
        return ToolRouter(
            settings=settings,
            mcp_client=InMemoryMCPClient(
                {"clause_extractor": clause_extractor, "risk_scorer": risk_scorer}
            ),
        )

    monkeypatch.setattr("src.api.server.ToolRouter", mock_router)

    client = TestClient(app)
    response = client.post(
        "/api/analyze",
        json={
            "contract_text": "1. Non-compete\nworldwide irrevocable perpetual restriction",
            "filename": "test.txt",
            "no_human_gate": False,
            "human_gate_threshold": "HIGH",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["pending_human_review"] is True
    session_id = data["session_id"]
    assert session_id in _pending_sessions
