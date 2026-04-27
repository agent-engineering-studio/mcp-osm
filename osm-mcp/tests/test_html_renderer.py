"""HTML rendering tests — verify output is valid, self-contained, and embeds GeoJSON."""

import pytest

from osm_mcp.html_renderer import MapLayer, render_map


@pytest.fixture
def sample_layers():
    return [
        MapLayer(
            name="Bus stops",
            geojson={"type": "FeatureCollection", "features": [
                {"type": "Feature",
                 "geometry": {"type": "Point", "coordinates": [11.25, 43.77]},
                 "properties": {"name": "Stazione SMN"}},
            ]},
            style={"color": "#e6194B", "weight": 2, "fillOpacity": 0.5, "radius": 6},
        ),
        MapLayer(
            name="Tram lines",
            geojson={"type": "FeatureCollection", "features": [
                {"type": "Feature",
                 "geometry": {"type": "LineString", "coordinates": [[11.20, 43.77], [11.30, 43.78]]},
                 "properties": {"line": "T1"}},
            ]},
            style={"color": "#3cb44b", "weight": 3, "fillOpacity": 0.5, "radius": 6},
        ),
    ]


def test_render_map_produces_valid_html(sample_layers):
    html = render_map(sample_layers, title="Test")
    assert html.startswith("<!doctype html>") or html.startswith("<!DOCTYPE html>")
    assert "</html>" in html
    assert "<title>Test</title>" in html


def test_render_map_embeds_layer_names(sample_layers):
    html = render_map(sample_layers, title="Test")
    assert "Bus stops" in html
    assert "Tram lines" in html


def test_render_map_includes_leaflet_cdn(sample_layers):
    html = render_map(sample_layers)
    assert "unpkg.com/leaflet" in html


def test_render_map_uses_default_osm_tile_url(sample_layers):
    html = render_map(sample_layers)
    assert "tile.openstreetmap.org" in html


def test_render_map_embeds_geojson_coordinates(sample_layers):
    html = render_map(sample_layers)
    # Coordinates should appear in the embedded JSON
    assert "11.25" in html
    assert "43.77" in html


def test_render_map_with_explicit_center_and_zoom(sample_layers):
    html = render_map(sample_layers, center=(41.9, 12.5), zoom=10)
    assert "41.9" in html and "12.5" in html
    assert "10" in html


def test_render_map_escapes_title_special_chars(sample_layers):
    html = render_map(sample_layers, title='"X" & <script>alert(1)</script>')
    # Jinja2 |e filter should escape these
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html or "&amp;" in html
