"""Unit tests for geojson_builder — pure-Python validation, no I/O."""

import pytest

from osm_mcp.geojson_builder import (
    assign_layer_styles,
    compute_bounds,
    parse_geojson,
)


def test_parse_feature_collection_passthrough():
    fc = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature",
             "geometry": {"type": "Point", "coordinates": [12.5, 41.9]},
             "properties": {"name": "Rome"}}
        ],
    }
    out = parse_geojson(fc)
    assert out["type"] == "FeatureCollection"
    assert len(out["features"]) == 1


def test_parse_single_feature_wraps_into_collection():
    feature = {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [11.25, 43.77]},
        "properties": {},
    }
    out = parse_geojson(feature)
    assert out["type"] == "FeatureCollection"
    assert out["features"][0]["geometry"]["coordinates"] == [11.25, 43.77]


def test_parse_geometry_only_wraps_into_feature_collection():
    geom = {"type": "Point", "coordinates": [9.19, 45.46]}
    out = parse_geojson(geom)
    assert out["type"] == "FeatureCollection"
    assert out["features"][0]["geometry"] == geom


def test_parse_string_input_decoded_as_json():
    raw = '{"type":"FeatureCollection","features":[]}'
    out = parse_geojson(raw)
    assert out["features"] == []


def test_parse_rejects_malformed_string():
    with pytest.raises(ValueError, match="invalid|malformed|JSON"):
        parse_geojson("not json")


def test_parse_drops_invalid_features_silently():
    fc = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [0, 0]},
             "properties": {}},
            {"type": "Feature", "geometry": None, "properties": {}},  # invalid
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [1, 1]},
             "properties": {}},
        ],
    }
    out = parse_geojson(fc)
    assert len(out["features"]) == 2


def test_compute_bounds_for_points():
    fc = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [10.0, 40.0]}, "properties": {}},
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [12.0, 42.0]}, "properties": {}},
        ],
    }
    south, west, north, east = compute_bounds(fc)
    assert south == 40.0 and north == 42.0
    assert west == 10.0 and east == 12.0


def test_compute_bounds_empty_returns_italy_default():
    south, west, north, east = compute_bounds({"type": "FeatureCollection", "features": []})
    # Italy bbox approx: 35.5, 6.6, 47.1, 18.5
    assert 35 < south < 38 and 45 < north < 48
    assert 6 < west < 8 and 17 < east < 19


def test_assign_layer_styles_returns_distinct_colors():
    styles = assign_layer_styles(5)
    assert len(styles) == 5
    colors = [s["color"] for s in styles]
    assert len(set(colors)) == 5


def test_assign_layer_styles_cycles_when_more_than_palette():
    styles = assign_layer_styles(20)
    assert len(styles) == 20
