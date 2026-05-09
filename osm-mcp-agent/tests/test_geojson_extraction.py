"""Tests for deterministic GeoJSON extraction from MCP tool results.

Verifies that _process_agent_response correctly builds ChatResponse
with text summary + GeoJSON/HTML resources from tool outputs.
"""
import json
from types import SimpleNamespace

from osm_agent.api import (
    _build_descriptions,
    _build_resources_from_tool_outputs,
    _extract_tool_outputs,
    _get_assistant_text,
    _parse_mcp_output,
    _process_agent_response,
    _tool_data_to_features,
)
from osm_agent.preview import build_preview_html


# ── Helpers ─────────────────────────────────────────────────────────────


def _make_response(assistant_text: str, tool_results=None):
    """Build a minimal AgentResponse-like object."""
    messages = []
    for tool_name, output in (tool_results or []):
        content = SimpleNamespace(
            type="mcp_server_tool_result",
            tool_name=tool_name,
            output=output,
        )
        messages.append(SimpleNamespace(role="tool", contents=[content], text=""))
    messages.append(SimpleNamespace(
        role="assistant",
        contents=[SimpleNamespace(type="text", text=assistant_text)],
        text=assistant_text,
    ))
    return SimpleNamespace(messages=messages, text=assistant_text)


# ── _parse_mcp_output ──────────────────────────────────────────────────


def test_parse_mcp_output_string():
    data, resources = _parse_mcp_output('{"results": [{"lat": 1}], "count": 1}')
    assert data == {"results": [{"lat": 1}], "count": 1}
    assert resources == []


def test_parse_mcp_output_dict():
    data, resources = _parse_mcp_output({"results": [], "count": 0})
    assert data == {"results": [], "count": 0}


def test_parse_mcp_output_content_blocks():
    blocks = [
        {"type": "text", "text": '{"type":"single_layer_map","feature_count":2}'},
        {"type": "resource", "resource": {
            "uri": "osm://maps/single-abc",
            "mimeType": "text/html",
            "text": "<html>map</html>",
        }},
    ]
    data, resources = _parse_mcp_output(blocks)
    assert data == {"type": "single_layer_map", "feature_count": 2}
    assert len(resources) == 1
    assert resources[0]["resource"]["mimeType"] == "text/html"


def test_parse_mcp_output_invalid_string():
    data, resources = _parse_mcp_output("not json")
    assert data is None
    assert resources == []


# ── _tool_data_to_features ─────────────────────────────────────────────


def test_geocode_to_features():
    data = {
        "results": [
            {"display_name": "Lahore, Punjab, Pakistan", "lat": 31.55, "lon": 74.34,
             "type": "city", "class": "place", "importance": 0.8},
            {"display_name": "Lahore Gate, Delhi", "lat": 28.65, "lon": 77.24,
             "type": "monument", "class": "historic", "importance": 0.3},
        ],
        "count": 2,
    }
    features = _tool_data_to_features("geocode_address", data)
    assert len(features) == 2
    assert features[0]["geometry"]["type"] == "Point"
    assert features[0]["geometry"]["coordinates"] == [74.34, 31.55]
    assert features[0]["properties"]["name"] == "Lahore, Punjab, Pakistan"


def test_geocode_zero_results():
    data = {"results": [], "count": 0}
    features = _tool_data_to_features("geocode_address", data)
    assert features == []


def test_reverse_geocode_to_feature():
    data = {
        "display_name": "Faridpur, Bangladesh",
        "lat": 23.6064, "lon": 89.8429,
        "type": "city", "address": {"country": "Bangladesh"},
    }
    features = _tool_data_to_features("reverse_geocode", data)
    assert len(features) == 1
    assert features[0]["geometry"]["coordinates"] == [89.8429, 23.6064]


def test_find_nearby_places_to_features():
    data = {
        "count": 2,
        "category": "restaurant",
        "places": [
            {"id": "node/1", "name": "Ristorante A", "lat": 45.0, "lon": 9.0,
             "category": "restaurant", "phone": "+39123"},
            {"id": "node/2", "name": "Ristorante B", "lat": 45.1, "lon": 9.1,
             "category": "restaurant"},
        ],
    }
    features = _tool_data_to_features("find_nearby_places", data)
    assert len(features) == 2
    assert features[0]["properties"]["category"] == "restaurant"
    assert features[0]["properties"]["phone"] == "+39123"


def test_route_to_feature():
    data = {
        "distance_m": 12000,
        "duration_s": 900,
        "profile": "driving",
        "geometry": {
            "type": "LineString",
            "coordinates": [[74.34, 31.55], [74.50, 31.60]],
        },
    }
    features = _tool_data_to_features("get_route", data)
    assert len(features) == 1
    assert features[0]["geometry"]["type"] == "LineString"
    assert features[0]["properties"]["distance_m"] == 12000


def test_route_error_no_features():
    data = {"error": "no route found", "code": "NoRoute"}
    features = _tool_data_to_features("get_route", data)
    assert features == []


def test_ev_charging_to_features():
    data = {
        "count": 1,
        "stations": [
            {"lat": 45.0, "lon": 9.0, "name": "Station X", "operator": "Enel",
             "capacity": "4", "power_kw": "50"},
        ],
    }
    features = _tool_data_to_features("find_ev_charging_stations", data)
    assert len(features) == 1
    assert features[0]["properties"]["operator"] == "Enel"


def test_suggest_meeting_point_to_feature():
    data = {
        "lat": 45.0, "lon": 9.0,
        "display_name": "Piazza Duomo, Milano",
        "max_travel_duration_s": 600,
    }
    features = _tool_data_to_features("suggest_meeting_point", data)
    assert len(features) == 1
    assert features[0]["properties"]["name"] == "Piazza Duomo, Milano"


def test_explore_area_to_features():
    data = {
        "center": {"lat": 45.0, "lon": 9.0, "address": "Milano Centro"},
        "radius_m": 800,
        "categories": {
            "restaurant": [
                {"name": "Rist A", "lat": 45.01, "lon": 9.01},
            ],
            "cafe": [],
        },
    }
    features = _tool_data_to_features("explore_area", data)
    assert len(features) == 2  # center + 1 restaurant
    center = [f for f in features if f["properties"].get("role") == "center"]
    assert len(center) == 1


def test_analyze_commute_to_features():
    data = {
        "home": {"lat": 45.0, "lon": 9.0},
        "work": {"lat": 45.5, "lon": 9.5},
        "modes": {},
    }
    features = _tool_data_to_features("analyze_commute", data)
    assert len(features) == 2
    roles = {f["properties"]["role"] for f in features}
    assert roles == {"home", "work"}


def test_unknown_tool_no_features():
    features = _tool_data_to_features("osm_health", {"status": "healthy"})
    assert features == []


# ── _extract_tool_outputs ──────────────────────────────────────────────


def test_extract_tool_outputs_from_response():
    resp = _make_response("Summary", tool_results=[
        ("geocode_address", '{"results": [{"lat": 31.55, "lon": 74.34}], "count": 1}'),
    ])
    outputs = _extract_tool_outputs(resp)
    assert len(outputs) == 1
    assert outputs[0][0] == "geocode_address"


def test_extract_tool_outputs_no_tools():
    resp = _make_response("Just text, no tools called")
    outputs = _extract_tool_outputs(resp)
    assert outputs == []


# ── _build_resources_from_tool_outputs ─────────────────────────────────


def test_build_geojson_resource_from_geocode():
    tool_outputs = [
        ("geocode_address", '{"results": [{"display_name": "Lahore", "lat": 31.55, "lon": 74.34}], "count": 1}'),
    ]
    resources, fc = _build_resources_from_tool_outputs(tool_outputs)
    assert len(resources) == 1
    assert resources[0].format == "GEOJSON"
    assert fc is not None
    assert fc["type"] == "FeatureCollection"
    assert len(fc["features"]) == 1
    assert fc["features"][0]["geometry"]["coordinates"] == [74.34, 31.55]


def test_build_html_resource_from_render_tool():
    tool_outputs = [
        ("render_geojson_map", [
            {"type": "text", "text": '{"type":"single_layer_map"}'},
            {"type": "resource", "resource": {
                "uri": "osm://maps/single-abc",
                "mimeType": "text/html",
                "text": "<!doctype html><html>map</html>",
            }},
        ]),
    ]
    resources, fc = _build_resources_from_tool_outputs(tool_outputs)
    assert len(resources) == 1
    assert resources[0].format == "HTML"
    assert "<!doctype html>" in resources[0].content
    assert fc is None


def test_build_both_geojson_and_html():
    tool_outputs = [
        ("geocode_address", '{"results": [{"lat": 31.55, "lon": 74.34, "display_name": "X"}], "count": 1}'),
        ("render_geojson_map", [
            {"type": "text", "text": '{"type":"single_layer_map"}'},
            {"type": "resource", "resource": {
                "uri": "osm://maps/single-def",
                "mimeType": "text/html",
                "text": "<html>map</html>",
            }},
        ]),
    ]
    resources, fc = _build_resources_from_tool_outputs(tool_outputs)
    assert len(resources) == 2
    formats = {r.format for r in resources}
    assert formats == {"GEOJSON", "HTML"}
    assert fc is not None


def test_build_empty_when_no_coordinates():
    tool_outputs = [
        ("osm_health", '{"status": "healthy", "nominatim": true}'),
    ]
    resources, fc = _build_resources_from_tool_outputs(tool_outputs)
    assert resources == []
    assert fc is None


# ── _get_assistant_text ────────────────────────────────────────────────


def test_get_assistant_text_clean():
    resp = _make_response("Lahore is a city in Punjab, Pakistan.")
    assert _get_assistant_text(resp) == "Lahore is a city in Punjab, Pakistan."


def test_get_assistant_text_strips_legacy_markers():
    resp = _make_response(
        'Lahore.\n<!--RESOURCES_JSON-->\n[{"name":"x"}]\n<!--/RESOURCES_JSON-->'
    )
    assert _get_assistant_text(resp) == "Lahore."


# ── _process_agent_response (full pipeline) ───────────────────────────


def test_process_response_geocode():
    """Full pipeline: geocode tool result → ChatResponse with text + GeoJSON."""
    resp = _make_response(
        "Lahore si trova nel Punjab, Pakistan, alle coordinate 31.55°N, 74.34°E.",
        tool_results=[
            ("geocode_address", json.dumps({
                "results": [
                    {"display_name": "Lahore, Punjab, Pakistan",
                     "lat": 31.55, "lon": 74.34, "type": "city"},
                ],
                "count": 1,
            })),
        ],
    )
    chat_resp = _process_agent_response(resp)

    assert "Lahore" in chat_resp.text
    assert "Punjab" in chat_resp.text
    assert len(chat_resp.resources) == 1
    assert chat_resp.resources[0].format == "GEOJSON"
    fc = json.loads(chat_resp.resources[0].content)
    assert fc["type"] == "FeatureCollection"
    assert fc["features"][0]["geometry"]["coordinates"] == [74.34, 31.55]


def test_process_response_not_found():
    """When geocode returns 0 results, resources should be empty."""
    resp = _make_response(
        "Nessun risultato trovato per 'Xyzopolis, Eritrea'.",
        tool_results=[
            ("geocode_address", json.dumps({"results": [], "count": 0})),
        ],
    )
    chat_resp = _process_agent_response(resp)
    assert "Nessun risultato" in chat_resp.text
    assert chat_resp.resources == []


def test_process_response_no_tools():
    """When no tools are called, resources should be empty."""
    resp = _make_response("Non ho capito la domanda.")
    chat_resp = _process_agent_response(resp)
    assert chat_resp.text == "Non ho capito la domanda."
    assert chat_resp.resources == []


def test_process_response_multiple_tools():
    """Multiple tool calls → features merged into single FeatureCollection."""
    resp = _make_response(
        "Found places near Lahore.",
        tool_results=[
            ("geocode_address", json.dumps({
                "results": [{"display_name": "Lahore", "lat": 31.55, "lon": 74.34}],
                "count": 1,
            })),
            ("find_nearby_places", json.dumps({
                "count": 2,
                "category": "restaurant",
                "places": [
                    {"id": "n/1", "name": "A", "lat": 31.56, "lon": 74.35},
                    {"id": "n/2", "name": "B", "lat": 31.57, "lon": 74.36},
                ],
            })),
        ],
    )
    chat_resp = _process_agent_response(resp)
    assert len(chat_resp.resources) == 1
    assert chat_resp.resources[0].format == "GEOJSON"
    fc = json.loads(chat_resp.resources[0].content)
    assert len(fc["features"]) == 3  # 1 geocode + 2 POIs


# ── _build_descriptions ───────────────────────────────────────────────


def test_build_descriptions_geocode():
    fc = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [74.34, 31.55]},
                "properties": {
                    "name": "Lahore, Punjab, Pakistan",
                    "country": "Pakistan",
                    "country_code": "pk",
                    "type": "city",
                },
            },
        ],
    }
    descs = _build_descriptions(fc)
    assert len(descs) == 1
    assert descs[0].name == "Lahore, Punjab, Pakistan"
    assert descs[0].type == "city"
    assert descs[0].lat == 31.55
    assert descs[0].lon == 74.34
    assert descs[0].country == "Pakistan"
    assert descs[0].country_code == "pk"


def test_build_descriptions_route():
    fc = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[9.0, 45.0], [9.5, 45.5], [10.0, 46.0]],
                },
                "properties": {
                    "name": "Driving route",
                    "distance_m": 12000,
                    "duration_s": 900,
                },
            },
        ],
    }
    descs = _build_descriptions(fc)
    assert len(descs) == 1
    assert descs[0].type == "route"
    assert descs[0].lat == 45.5  # midpoint
    assert descs[0].lon == 9.5
    assert descs[0].details["distance_m"] == 12000


def test_build_descriptions_poi():
    fc = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [9.0, 45.0]},
                "properties": {"name": "Ristorante A", "category": "restaurant"},
            },
        ],
    }
    descs = _build_descriptions(fc)
    assert len(descs) == 1
    assert descs[0].type == "poi"
    assert descs[0].details["category"] == "restaurant"


def test_build_descriptions_empty():
    assert _build_descriptions(None) == []
    assert _build_descriptions({"type": "FeatureCollection", "features": []}) == []


# ── build_preview_html ─────────────────────────────────────────────────


def test_preview_html_contains_leaflet():
    fc = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [9.19, 45.46]},
                "properties": {"name": "Milano"},
            },
        ],
    }
    html = build_preview_html(fc, "Milano preview")
    assert html is not None
    assert "leaflet" in html.lower()
    assert "FeatureCollection" in html
    assert "Milano preview" in html


def test_preview_html_none_when_empty():
    fc = {"type": "FeatureCollection", "features": []}
    assert build_preview_html(fc) is None


def test_preview_html_escapes_xss():
    fc = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [0, 0]},
                "properties": {"name": "Test"},
            },
        ],
    }
    html = build_preview_html(fc, '<script>alert("xss")</script>')
    assert "<script>alert" not in html
    assert "&lt;script&gt;" in html


def test_preview_html_auto_summary_from_features():
    fc = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [9.19, 45.46]},
                "properties": {"name": "Milano"},
            },
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [11.25, 43.77]},
                "properties": {"name": "Firenze"},
            },
        ],
    }
    html = build_preview_html(fc)
    assert html is not None
    assert "Milano" in html
    assert "Firenze" in html


# ── _process_agent_response with descriptions + preview ───────────────


def test_process_response_includes_description_and_preview():
    resp = _make_response(
        "Lahore is a city in Punjab, Pakistan.",
        tool_results=[
            ("geocode_address", json.dumps({
                "results": [
                    {"display_name": "Lahore, Punjab, Pakistan",
                     "lat": 31.55, "lon": 74.34, "type": "city",
                     "country": "Pakistan", "country_code": "pk"},
                ],
                "count": 1,
            })),
        ],
    )
    chat_resp = _process_agent_response(resp)

    # description populated
    assert len(chat_resp.description) == 1
    assert chat_resp.description[0].name == "Lahore, Punjab, Pakistan"
    assert chat_resp.description[0].lat == 31.55

    # preview_html generated
    assert chat_resp.preview_html is not None
    assert "leaflet" in chat_resp.preview_html.lower()
    assert "FeatureCollection" in chat_resp.preview_html


def test_process_response_no_preview_when_no_features():
    resp = _make_response(
        "Nessun risultato.",
        tool_results=[
            ("geocode_address", json.dumps({"results": [], "count": 0})),
        ],
    )
    chat_resp = _process_agent_response(resp)
    assert chat_resp.description == []
    assert chat_resp.preview_html is None
