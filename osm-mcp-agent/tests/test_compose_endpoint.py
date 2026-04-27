"""Verify POST /compose-map calls osm-mcp directly via httpx and parses
the multi-content response into ChatResponse shape."""
import json
from pathlib import Path

import pytest
import respx
from fastapi.testclient import TestClient
from httpx import Response

from osm_agent import api as api_module

FIXTURE = Path(__file__).parent / "fixtures" / "ckan_response.json"


@pytest.fixture
def mock_settings(monkeypatch):
    """Force a known MCP URL and skip the AgentSession startup.

    IMPORTANT: TestClient is used WITHOUT a context manager (no `with` block)
    so FastAPI's lifespan does not run. The monkeypatched globals are what
    the endpoint sees during the request.
    """
    monkeypatch.setenv("MCP_SERVER_URL", "http://test-mcp:8080/mcp")
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setattr(api_module, "_session", object())
    from osm_agent.config import get_settings
    monkeypatch.setattr(api_module, "_settings", get_settings())


@respx.mock
def test_compose_map_calls_mcp_and_returns_html(mock_settings):
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))

    mock_response = {
        "result": {
            "content": [
                {"type": "text", "text": json.dumps({"layer_count": 2, "total_features": 3})},
                {"type": "resource", "resource": {
                    "uri": "osm://maps/composed-abc",
                    "mimeType": "text/html",
                    "text": "<!doctype html><html>...mapped...</html>",
                }},
            ]
        }
    }
    respx.post("http://test-mcp:8080/mcp").mock(return_value=Response(200, json=mock_response))

    client = TestClient(api_module.app)  # NO `with` — skips lifespan
    resp = client.post("/compose-map", json=fixture)

    assert resp.status_code == 200
    body = resp.json()
    assert "text" in body
    assert len(body["resources"]) == 1
    r = body["resources"][0]
    assert r["format"] == "HTML"
    assert "<!doctype html>" in r["content"]


@respx.mock
def test_compose_map_handles_error_response(mock_settings):
    err = {
        "result": {
            "content": [
                {"type": "text", "text": json.dumps({"error": "no valid GeoJSON"})}
            ]
        }
    }
    respx.post("http://test-mcp:8080/mcp").mock(return_value=Response(200, json=err))

    client = TestClient(api_module.app)
    resp = client.post("/compose-map", json={
        "text": "skipped all",
        "resources": [{"name": "x", "format": "PDF"}],
    })
    assert resp.status_code == 200
    body = resp.json()
    assert "error" in body["text"]
    assert body["resources"] == []
