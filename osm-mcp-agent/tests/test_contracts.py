"""Verify Resource/ChatResponse mirror the ckan-mcp-agent JSON shape."""
import json
from pathlib import Path

from osm_agent.contracts import ChatResponse, ComposeMapRequest, Resource

FIXTURE = Path(__file__).parent / "fixtures" / "ckan_response.json"


def test_resource_accepts_ckan_shape():
    payload = {"name": "Bus stops", "url": "https://example/x.geojson",
               "format": "GEOJSON", "content": '{"type":"FeatureCollection","features":[]}'}
    r = Resource(**payload)
    assert r.format == "GEOJSON"
    assert r.content.startswith("{")


def test_resource_optional_url_and_content():
    r = Resource(name="x", format="PDF")
    assert r.url is None
    assert r.content is None


def test_chat_response_roundtrip_from_ckan_fixture():
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    resp = ChatResponse(**raw)
    assert resp.text
    assert len(resp.resources) >= 2
    assert any(r.format.upper() == "GEOJSON" for r in resp.resources)


def test_compose_map_request_accepts_chat_response():
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    req = ComposeMapRequest(**raw)
    assert req.text == raw["text"]
    assert len(req.resources) == len(raw["resources"])
