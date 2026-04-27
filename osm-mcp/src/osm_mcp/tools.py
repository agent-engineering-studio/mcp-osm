"""Tool implementations — pure business logic, returned as JSON strings."""

from __future__ import annotations

import json
import uuid as _uuid
from typing import Any

from mcp.types import EmbeddedResource, TextContent, TextResourceContents
from pydantic import AnyUrl

from osm_mcp import geojson_builder as _gjb
from osm_mcp import html_renderer as _hr
from osm_mcp import osm_client


def _json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)


def _summarise_element(el: dict[str, Any]) -> dict[str, Any]:
    """Normalise an Overpass element to a compact POI record."""
    tags = el.get("tags", {}) or {}
    if el.get("type") == "node":
        lat, lon = el.get("lat"), el.get("lon")
    else:
        center = el.get("center") or {}
        lat, lon = center.get("lat"), center.get("lon")
    return {
        "id": f"{el.get('type', 'node')}/{el.get('id')}",
        "name": tags.get("name") or tags.get("brand") or tags.get("operator"),
        "category": tags.get("amenity") or tags.get("shop") or tags.get("tourism")
                    or tags.get("leisure") or tags.get("railway"),
        "lat": lat,
        "lon": lon,
        "address": {
            "street": tags.get("addr:street"),
            "housenumber": tags.get("addr:housenumber"),
            "city": tags.get("addr:city"),
            "postcode": tags.get("addr:postcode"),
            "country": tags.get("addr:country"),
        },
        "phone": tags.get("phone") or tags.get("contact:phone"),
        "website": tags.get("website") or tags.get("contact:website"),
        "opening_hours": tags.get("opening_hours"),
        "tags": tags,
    }


# ── Tools ───────────────────────────────────────────────────────────

async def geocode_address(address: str, limit: int = 5) -> str:
    results = await osm_client.geocode(address, limit=limit)
    out = [
        {
            "display_name": r.get("display_name"),
            "lat": float(r["lat"]),
            "lon": float(r["lon"]),
            "type": r.get("type"),
            "class": r.get("class"),
            "importance": r.get("importance"),
            "bbox": r.get("boundingbox"),
            "address": r.get("address", {}),
        }
        for r in results
    ]
    return _json({"results": out, "count": len(out)})


async def reverse_geocode(lat: float, lon: float, zoom: int = 18) -> str:
    data = await osm_client.reverse_geocode(lat, lon, zoom=zoom)
    return _json(
        {
            "display_name": data.get("display_name"),
            "address": data.get("address", {}),
            "lat": float(data.get("lat", lat)),
            "lon": float(data.get("lon", lon)),
            "type": data.get("type"),
            "class": data.get("class"),
        }
    )


async def find_nearby_places(
    lat: float, lon: float, radius_m: int = 1000, category: str = "restaurant", limit: int = 20
) -> str:
    elements = await osm_client.overpass_around(lat, lon, radius_m, category, limit=limit)
    places = [_summarise_element(el) for el in elements]
    return _json({"count": len(places), "places": places, "category": category})


async def search_category_in_bbox(
    south: float, west: float, north: float, east: float, category: str, limit: int = 50
) -> str:
    elements = await osm_client.overpass_bbox(south, west, north, east, category, limit=limit)
    places = [_summarise_element(el) for el in elements]
    return _json({"count": len(places), "places": places, "category": category})


async def get_route(
    start_lat: float,
    start_lon: float,
    end_lat: float,
    end_lon: float,
    profile: str = "driving",
    steps: bool = True,
) -> str:
    data = await osm_client.osrm_route(
        (start_lat, start_lon),
        (end_lat, end_lon),
        profile=profile,  # type: ignore[arg-type]
        steps=steps,
    )
    if not data.get("routes"):
        return _json({"error": "no route found", "code": data.get("code")})
    route = data["routes"][0]
    legs = route.get("legs", [])
    turn_by_turn: list[dict[str, Any]] = []
    for leg in legs:
        for st in leg.get("steps", []):
            turn_by_turn.append(
                {
                    "distance_m": st.get("distance"),
                    "duration_s": st.get("duration"),
                    "name": st.get("name"),
                    "maneuver": (st.get("maneuver") or {}).get("type"),
                    "modifier": (st.get("maneuver") or {}).get("modifier"),
                    "instruction": (st.get("maneuver") or {}).get("instruction"),
                }
            )
    return _json(
        {
            "distance_m": route.get("distance"),
            "duration_s": route.get("duration"),
            "profile": profile,
            "geometry": route.get("geometry"),
            "steps": turn_by_turn if steps else [],
        }
    )


async def suggest_meeting_point(
    points: list[list[float]], profile: str = "driving"
) -> str:
    """Given N participant coordinates, propose a meeting location that
    minimises the maximum travel duration (fair-share heuristic)."""
    if len(points) < 2:
        return _json({"error": "at least 2 points required"})

    pts: list[tuple[float, float]] = [(float(p[0]), float(p[1])) for p in points]
    # Centroid seed candidate
    c_lat = sum(p[0] for p in pts) / len(pts)
    c_lon = sum(p[1] for p in pts) / len(pts)
    candidates = pts + [(c_lat, c_lon)]

    table = await osm_client.osrm_table(candidates, profile=profile)  # type: ignore[arg-type]
    durations: list[list[float]] = table.get("durations") or []

    if not durations:
        return _json({"error": "OSRM table query failed", "code": table.get("code")})

    n = len(pts)
    best_idx: int | None = None
    best_score: float = float("inf")
    for cand_i in range(len(candidates)):
        max_dur = max(durations[src][cand_i] or 0 for src in range(n))
        if max_dur < best_score:
            best_score = max_dur
            best_idx = cand_i

    assert best_idx is not None
    lat, lon = candidates[best_idx]

    address = await osm_client.reverse_geocode(lat, lon)
    return _json(
        {
            "lat": lat,
            "lon": lon,
            "display_name": address.get("display_name"),
            "max_travel_duration_s": best_score,
            "profile": profile,
            "from_centroid": best_idx == len(pts),
        }
    )


async def explore_area(lat: float, lon: float, radius_m: int = 800) -> str:
    """Small digest of the area: top POIs across common categories."""
    categories = ["restaurant", "cafe", "park", "supermarket", "pharmacy", "school"]
    summary: dict[str, list[dict[str, Any]]] = {}
    for cat in categories:
        elements = await osm_client.overpass_around(lat, lon, radius_m, cat, limit=10)
        summary[cat] = [_summarise_element(e) for e in elements[:10]]
    address = await osm_client.reverse_geocode(lat, lon)
    return _json(
        {
            "center": {"lat": lat, "lon": lon, "address": address.get("display_name")},
            "radius_m": radius_m,
            "categories": summary,
        }
    )


async def find_ev_charging_stations(
    lat: float, lon: float, radius_m: int = 5000, limit: int = 30
) -> str:
    elements = await osm_client.overpass_around(lat, lon, radius_m, "ev_charging", limit=limit)
    stations = []
    for el in elements:
        rec = _summarise_element(el)
        tags = el.get("tags", {}) or {}
        rec["capacity"] = tags.get("capacity")
        rec["socket_types"] = {k: v for k, v in tags.items() if k.startswith("socket:")}
        rec["power_kw"] = tags.get("charging_station:output") or tags.get("maxpower")
        rec["operator"] = tags.get("operator")
        rec["fee"] = tags.get("fee")
        stations.append(rec)
    return _json({"count": len(stations), "stations": stations})


async def analyze_commute(
    home_lat: float, home_lon: float, work_lat: float, work_lon: float
) -> str:
    profiles = ["driving", "walking", "cycling"]
    results = {}
    for p in profiles:
        data = await osm_client.osrm_route(
            (home_lat, home_lon), (work_lat, work_lon), profile=p, steps=False  # type: ignore[arg-type]
        )
        if data.get("routes"):
            r = data["routes"][0]
            results[p] = {
                "distance_km": round((r.get("distance") or 0) / 1000, 2),
                "duration_min": round((r.get("duration") or 0) / 60, 1),
            }
        else:
            results[p] = {"error": data.get("code", "no route")}
    return _json(
        {
            "home": {"lat": home_lat, "lon": home_lon},
            "work": {"lat": work_lat, "lon": work_lon},
            "modes": results,
        }
    )


# ══════════════════════════════════════════════════════════════════════════
#  Map rendering — added in Task 6
# ══════════════════════════════════════════════════════════════════════════


def _summary_block(payload: dict[str, Any]) -> TextContent:
    """Wrap a JSON-serialisable summary as a TextContent block."""
    return TextContent(type="text", text=json.dumps(payload, ensure_ascii=False))


def _html_block(html: str, kind: str = "map") -> EmbeddedResource:
    """Wrap an HTML string as an EmbeddedResource with mimeType=text/html."""
    return EmbeddedResource(
        type="resource",
        resource=TextResourceContents(
            uri=AnyUrl(f"osm://maps/{kind}-{_uuid.uuid4().hex[:8]}"),
            mimeType="text/html",
            text=html,
        ),
    )


async def render_geojson_map(
    geojson: dict[str, Any] | str,
    title: str | None = None,
    center: list[float] | None = None,
    zoom: int | None = None,
) -> list[TextContent | EmbeddedResource]:
    """Render a single-layer Leaflet HTML map from a GeoJSON value.

    Returns multi-content: text summary + HTML resource (mimeType=text/html).
    """
    fc = _gjb.parse_geojson(geojson)
    style = _gjb.assign_layer_styles(1)[0]
    layer = _hr.MapLayer(name=title or "Layer", geojson=fc, style=style)
    bounds = _gjb.compute_bounds(fc)
    summary = {
        "type": "single_layer_map",
        "feature_count": len(fc["features"]),
        "bounds": list(bounds),
        "title": title,
    }
    html = _hr.render_map(
        [layer], title=title,
        center=tuple(center) if center else None, zoom=zoom,
    )
    return [_summary_block(summary), _html_block(html, kind="single")]


async def render_multi_layer_map(
    layers: list[dict[str, Any]],
    title: str | None = None,
    center: list[float] | None = None,
    zoom: int | None = None,
) -> list[TextContent | EmbeddedResource]:
    """Render an HTML map with multiple GeoJSON layers, each named and styled."""
    palette = _gjb.assign_layer_styles(len(layers))
    map_layers: list[_hr.MapLayer] = []
    feat_counts: list[dict[str, Any]] = []
    for i, layer in enumerate(layers):
        fc = _gjb.parse_geojson(layer["geojson"])
        style = layer.get("style") or palette[i]
        name = layer.get("name") or f"Layer {i + 1}"
        map_layers.append(_hr.MapLayer(name=name, geojson=fc, style=style))
        feat_counts.append({"name": name, "features": len(fc["features"])})

    summary = {
        "type": "multi_layer_map",
        "layer_count": len(map_layers),
        "total_features": sum(c["features"] for c in feat_counts),
        "layers": feat_counts,
    }
    html = _hr.render_map(map_layers, title=title,
                          center=tuple(center) if center else None, zoom=zoom)
    return [_summary_block(summary), _html_block(html, kind="multi")]


async def compose_map_from_resources(
    text: str,
    resources: list[dict[str, Any]],
    title: str | None = None,
    center: list[float] | None = None,
    zoom: int | None = None,
) -> list[TextContent | EmbeddedResource]:
    """Take a CKAN-agent-style payload and render a multi-layer map.

    Filters resources where format=='GEOJSON' (case-insensitive) with non-empty
    content. Non-GeoJSON entries are reported in summary.skipped[]. Stateless,
    deterministic, no LLM.
    """
    palette_size = sum(
        1 for r in resources
        if (r.get("format") or "").upper() == "GEOJSON" and r.get("content")
    )
    palette = _gjb.assign_layer_styles(max(palette_size, 1))

    layers: list[_hr.MapLayer] = []
    skipped: list[dict[str, Any]] = []
    pi = 0
    for r in resources:
        fmt = (r.get("format") or "").upper()
        if fmt != "GEOJSON" or not r.get("content"):
            skipped.append({
                "name": r.get("name"), "format": fmt or None,
                "url": r.get("url"),
            })
            continue
        try:
            fc = _gjb.parse_geojson(r["content"])
        except ValueError as exc:
            skipped.append({"name": r.get("name"), "format": fmt, "error": str(exc)})
            continue
        layers.append(_hr.MapLayer(
            name=r.get("name") or f"Layer {pi + 1}",
            geojson=fc,
            style=palette[pi],
        ))
        pi += 1

    if not layers:
        return [_summary_block({
            "error": "no valid GeoJSON layers found",
            "skipped": skipped,
        })]

    summary = {
        "type": "composed_map",
        "layer_count": len(layers),
        "total_features": sum(len(layer.geojson.get("features", [])) for layer in layers),
        "skipped": skipped,
        "layers": [
            {"name": layer.name, "features": len(layer.geojson.get("features", []))}
            for layer in layers
        ],
    }
    html = _hr.render_map(
        layers,
        title=title or (text[:80] if text else "Composed Map"),
        center=tuple(center) if center else None,
        zoom=zoom,
    )
    return [_summary_block(summary), _html_block(html, kind="composed")]
