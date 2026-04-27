"""GeoJSON parsing, validation, normalization and styling utilities.

Pure Python, no I/O, no network. All functions are deterministic and side-effect
free. The module sits between the OSM tool layer (which produces raw
JSON dicts) and the rendering layer (which expects FeatureCollections + styles).

CRS policy: GeoJSON RFC 7946 mandates WGS84 (EPSG:4326). Inputs declaring a
different CRS via the (deprecated) "crs" member are rejected with a clear
ValueError. Automatic reprojection is out of scope.
"""
from __future__ import annotations

import json
import logging
from typing import Any

log = logging.getLogger(__name__)

# Italy default bbox used when an empty FeatureCollection is given to
# compute_bounds. Avoids div-by-zero when callers blindly fitBounds().
_ITALY_BBOX: tuple[float, float, float, float] = (35.5, 6.6, 47.1, 18.5)

# 12-color palette (high-contrast, color-blind friendly).
_PALETTE: list[str] = [
    "#e6194B", "#3cb44b", "#4363d8", "#f58231", "#911eb4", "#42d4f4",
    "#f032e6", "#469990", "#9A6324", "#800000", "#808000", "#000075",
]


def parse_geojson(raw: str | dict[str, Any]) -> dict[str, Any]:
    """Parse and normalize a GeoJSON input into a FeatureCollection dict.

    Accepts JSON strings, FeatureCollection dicts, single Feature dicts, and
    raw Geometry dicts. Wraps non-collection inputs as needed.

    Strips features whose geometry is None or invalid (logs a warning with the
    count). Rejects non-WGS84 CRS declarations with ValueError.
    """
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid GeoJSON string: {exc}") from exc
    else:
        data = raw

    if not isinstance(data, dict):
        raise ValueError(f"GeoJSON must be a JSON object, got {type(data).__name__}")

    _reject_non_wgs84(data)

    gtype = data.get("type")
    if gtype == "FeatureCollection":
        fc = data
    elif gtype == "Feature":
        fc = {"type": "FeatureCollection", "features": [data]}
    elif gtype in {"Point", "LineString", "Polygon", "MultiPoint",
                   "MultiLineString", "MultiPolygon", "GeometryCollection"}:
        fc = {
            "type": "FeatureCollection",
            "features": [{"type": "Feature", "geometry": data, "properties": {}}],
        }
    else:
        raise ValueError(f"unsupported GeoJSON type: {gtype!r}")

    raw_features = list(fc.get("features") or [])
    valid = [f for f in raw_features if _is_valid_feature(f)]
    dropped = len(raw_features) - len(valid)
    if dropped:
        log.warning("geojson_builder: dropped %d invalid features", dropped)
    return {"type": "FeatureCollection", "features": valid}


def _reject_non_wgs84(data: dict[str, Any]) -> None:
    crs = data.get("crs")
    if not crs:
        return
    name = (crs.get("properties") or {}).get("name") or ""
    if "CRS84" in name or "4326" in name or "WGS" in name.upper():
        return
    raise ValueError(
        f"non-WGS84 CRS not supported (got {name!r}); "
        "please reproject to EPSG:4326 (RFC 7946)"
    )


def _is_valid_feature(feature: dict[str, Any]) -> bool:
    if feature.get("type") != "Feature":
        return False
    geom = feature.get("geometry")
    if not isinstance(geom, dict):
        return False
    coords = geom.get("coordinates")
    if coords is None and geom.get("type") != "GeometryCollection":
        return False
    return True


def compute_bounds(geojson: dict[str, Any]) -> tuple[float, float, float, float]:
    """Return (south, west, north, east) bbox of a FeatureCollection.

    For empty collections returns Italy's default bbox so map fits gracefully.
    """
    south = +90.0
    north = -90.0
    west = +180.0
    east = -180.0
    has_any = False
    for feat in geojson.get("features", []):
        for lon, lat in _iter_coords(feat.get("geometry") or {}):
            has_any = True
            if lat < south:
                south = lat
            if lat > north:
                north = lat
            if lon < west:
                west = lon
            if lon > east:
                east = lon
    if not has_any:
        return _ITALY_BBOX
    return (south, west, north, east)


def _iter_coords(geom: dict[str, Any]):
    """Yield (lon, lat) pairs from any GeoJSON geometry."""
    gtype = geom.get("type")
    coords = geom.get("coordinates")
    if gtype == "Point" and coords is not None:
        yield (coords[0], coords[1])
    elif gtype in {"LineString", "MultiPoint"}:
        for c in coords or []:
            yield (c[0], c[1])
    elif gtype in {"Polygon", "MultiLineString"}:
        for ring in coords or []:
            for c in ring:
                yield (c[0], c[1])
    elif gtype == "MultiPolygon":
        for poly in coords or []:
            for ring in poly:
                for c in ring:
                    yield (c[0], c[1])
    elif gtype == "GeometryCollection":
        for g in geom.get("geometries", []):
            yield from _iter_coords(g)


def assign_layer_styles(count: int) -> list[dict[str, Any]]:
    """Return N distinct Leaflet style dicts. Cycles palette if N > 12."""
    return [
        {"color": _PALETTE[i % len(_PALETTE)],
         "weight": 2,
         "fillOpacity": 0.5,
         "radius": 6}
        for i in range(count)
    ]
