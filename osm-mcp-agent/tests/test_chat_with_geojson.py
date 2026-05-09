"""Verify multipart geojson upload prepends the file content to the prompt."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from osm_agent import api as api_module


def _fake_response(assistant_text: str, tool_results=None):
    """Build a minimal AgentResponse-like object for testing.

    Mirrors agent_framework's real shape: a FunctionCallContent
    (type='function_call') paired with a FunctionResultContent
    (type='function_result'), correlated by call_id.
    """
    messages = []
    for i, (tool_name, output) in enumerate(tool_results or []):
        call_id = f"call_{i}"
        call = SimpleNamespace(type="function_call", call_id=call_id, name=tool_name)
        result = SimpleNamespace(type="function_result", call_id=call_id, result=output)
        messages.append(SimpleNamespace(role="tool", contents=[call, result], text=""))
    messages.append(SimpleNamespace(
        role="assistant",
        contents=[SimpleNamespace(type="text", text=assistant_text)],
        text=assistant_text,
    ))
    return SimpleNamespace(messages=messages, text=assistant_text)


@pytest.fixture
def mock_session(monkeypatch):
    """Replace _session with an AsyncMock that captures the prompt.

    IMPORTANT: TestClient is used WITHOUT a context manager so FastAPI's
    lifespan does not run.
    """
    fake = AsyncMock()
    # Simulate a render_geojson_map tool result with HTML resource
    tool_results = [
        ("render_geojson_map", [
            {"type": "text", "text": '{"type":"single_layer_map","feature_count":0}'},
            {"type": "resource", "resource": {
                "uri": "osm://maps/single-abc",
                "mimeType": "text/html",
                "text": "<html>...</html>",
            }},
        ]),
    ]
    fake.run_full = AsyncMock(return_value=_fake_response(
        "Map produced.", tool_results=tool_results,
    ))
    monkeypatch.setattr(api_module, "_session", fake)
    from osm_agent.config import get_settings
    monkeypatch.setattr(api_module, "_settings", get_settings())
    return fake


def test_chat_with_geojson_prepends_file_content_to_prompt(mock_session):
    geojson_str = '{"type":"FeatureCollection","features":[]}'
    files = {
        "geojson_file": ("track.geojson", geojson_str, "application/geo+json"),
    }
    data = {"message": "Render this on a map"}
    client = TestClient(api_module.app)  # NO `with` — skip lifespan
    resp = client.post("/chat/with-geojson", data=data, files=files)
    assert resp.status_code == 200
    body = resp.json()
    assert body["resources"][0]["format"] == "HTML"

    sent = mock_session.run_full.await_args.args[0]
    assert "USER QUERY: Render this on a map" in sent
    assert "ATTACHED GEOJSON" in sent
    assert geojson_str in sent
