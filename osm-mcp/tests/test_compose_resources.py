"""Unit tests for the 3 new map-rendering tool functions in tools.py.

These call the business-logic functions directly (not via FastMCP). The MCP
registration in server.py is verified separately by the smoke integration test
in CI (Task 18).
"""
import json
from pathlib import Path

import pytest

from osm_mcp.tools import (
    compose_map_from_resources,
    render_geojson_map,
    render_multi_layer_map,
)

FIXTURE = Path(__file__).parent / "fixtures" / "ckan_response.json"


def _summary(blocks):
    """Extract the parsed JSON summary from the first TextContent block."""
    text_block = blocks[0]
    return json.loads(text_block.text)


def _html(blocks):
    """Extract the HTML string from the EmbeddedResource block."""
    res_block = blocks[1]
    return res_block.resource.text


@pytest.mark.asyncio
async def test_render_geojson_map_single_feature():
    fc = {"type": "FeatureCollection", "features": [
        {"type": "Feature",
         "geometry": {"type": "Point", "coordinates": [12.5, 41.9]},
         "properties": {"name": "Roma"}},
    ]}
    blocks = await render_geojson_map(geojson=fc, title="Test")
    assert len(blocks) == 2
    summary = _summary(blocks)
    assert summary["feature_count"] == 1
    html = _html(blocks)
    assert "<!doctype html>" in html.lower() or "<!DOCTYPE html>" in html
    assert "Roma" in html


@pytest.mark.asyncio
async def test_render_multi_layer_map_two_layers():
    layers = [
        {"name": "L1", "geojson": {"type": "FeatureCollection", "features": [
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [11, 43]}, "properties": {}}]}},
        {"name": "L2", "geojson": {"type": "FeatureCollection", "features": [
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [12, 44]}, "properties": {}}]}},
    ]
    blocks = await render_multi_layer_map(layers=layers, title="Multi")
    summary = _summary(blocks)
    assert summary["layer_count"] == 2
    html = _html(blocks)
    assert "L1" in html and "L2" in html


@pytest.mark.asyncio
async def test_compose_map_filters_non_geojson():
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    blocks = await compose_map_from_resources(
        text=payload["text"],
        resources=payload["resources"],
    )
    summary = _summary(blocks)
    assert summary["layer_count"] == 2  # 2 GEOJSON, 1 PDF skipped
    assert len(summary["skipped"]) == 1
    assert summary["skipped"][0]["format"] == "PDF"
    html = _html(blocks)
    assert "Bus stops Florence" in html
    assert "Tramway lines" in html


@pytest.mark.asyncio
async def test_compose_map_returns_error_when_no_geojson():
    blocks = await compose_map_from_resources(
        text="all skipped",
        resources=[
            {"name": "x", "format": "PDF", "url": "https://example/x.pdf"},
        ],
    )
    # When no GeoJSON layers, only the text block (no HTML resource)
    assert len(blocks) == 1
    summary = _summary(blocks)
    assert "error" in summary
