"""Verify multipart geojson upload prepends the file content to the prompt."""
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from osm_agent import api as api_module


@pytest.fixture
def mock_session(monkeypatch):
    """Replace _session with an AsyncMock that captures the prompt.

    IMPORTANT: TestClient is used WITHOUT a context manager so FastAPI's
    lifespan does not run.
    """
    fake = AsyncMock()
    fake.run = AsyncMock(return_value=(
        "Map produced.\n<!--RESOURCES_JSON-->\n["
        '{"name":"map.html","format":"HTML","content":"<html>...</html>"}'
        "]\n<!--/RESOURCES_JSON-->"
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

    sent = mock_session.run.await_args.args[0]
    assert "USER QUERY: Render this on a map" in sent
    assert "ATTACHED GEOJSON" in sent
    assert geojson_str in sent
