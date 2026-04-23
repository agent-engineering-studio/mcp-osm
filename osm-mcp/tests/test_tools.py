"""Smoke tests for the OSM MCP tool layer.

These tests mock httpx with respx, so no network traffic is required.
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from osm_mcp import tools
from osm_mcp.config import settings


@pytest.mark.asyncio
@respx.mock
async def test_geocode_address():
    respx.get(f"{settings.NOMINATIM_URL}/search").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "display_name": "Milan, Italy",
                    "lat": "45.4642",
                    "lon": "9.19",
                    "type": "city",
                    "class": "place",
                    "importance": 0.9,
                    "boundingbox": ["45.3", "45.6", "9.0", "9.3"],
                    "address": {"city": "Milan", "country": "Italy"},
                }
            ],
        )
    )
    raw = await tools.geocode_address("Milan")
    data = json.loads(raw)
    assert data["count"] == 1
    assert data["results"][0]["lat"] == pytest.approx(45.4642)
    assert data["results"][0]["address"]["country"] == "Italy"


@pytest.mark.asyncio
@respx.mock
async def test_find_nearby_places_normalises_elements():
    respx.post(settings.OVERPASS_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "elements": [
                    {
                        "type": "node",
                        "id": 1,
                        "lat": 45.46,
                        "lon": 9.19,
                        "tags": {
                            "amenity": "restaurant",
                            "name": "Trattoria Milanese",
                            "addr:city": "Milano",
                        },
                    },
                    {
                        "type": "way",
                        "id": 42,
                        "center": {"lat": 45.47, "lon": 9.20},
                        "tags": {"amenity": "restaurant", "name": "Ristorante Duomo"},
                    },
                ]
            },
        )
    )
    raw = await tools.find_nearby_places(45.46, 9.19, 800, "restaurant", 10)
    data = json.loads(raw)
    assert data["count"] == 2
    assert data["places"][0]["name"] == "Trattoria Milanese"
    assert data["places"][1]["id"] == "way/42"


@pytest.mark.asyncio
@respx.mock
async def test_get_route_returns_distance_and_steps():
    respx.get(url__regex=rf"{settings.OSRM_URL}/route/v1/.*").mock(
        return_value=httpx.Response(
            200,
            json={
                "routes": [
                    {
                        "distance": 5000,
                        "duration": 600,
                        "geometry": {"type": "LineString", "coordinates": []},
                        "legs": [
                            {
                                "steps": [
                                    {
                                        "distance": 500,
                                        "duration": 60,
                                        "name": "Via Roma",
                                        "maneuver": {
                                            "type": "turn",
                                            "modifier": "left",
                                            "instruction": "Turn left onto Via Roma",
                                        },
                                    }
                                ]
                            }
                        ],
                    }
                ]
            },
        )
    )
    raw = await tools.get_route(45.46, 9.19, 45.48, 9.21)
    data = json.loads(raw)
    assert data["distance_m"] == 5000
    assert data["duration_s"] == 600
    assert data["steps"][0]["name"] == "Via Roma"
