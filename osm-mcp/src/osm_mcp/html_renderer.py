"""Render a self-contained Leaflet HTML map from one or more GeoJSON layers.

Output is a complete <!doctype html>...</html> string with Leaflet from CDN
and OSM raster tiles. No external assets to host. ~5-50 KB depending on
embedded GeoJSON size.

Style/layer dataclass is intentionally minimal — paint logic lives in the
template, not in Python.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from osm_mcp.config import settings

_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
_env = Environment(
    loader=FileSystemLoader(_TEMPLATE_DIR),
    autoescape=select_autoescape(["html", "j2"]),
)


@dataclass
class MapLayer:
    name: str
    geojson: dict[str, Any]
    style: dict[str, Any] | None = None


_DEFAULT_STYLE: dict[str, Any] = {"color": "#3388ff", "weight": 2, "fillOpacity": 0.4, "radius": 6}


def render_map(
    layers: list[MapLayer],
    title: str | None = None,
    center: tuple[float, float] | None = None,
    zoom: int | None = None,
    attribution: str | None = None,
) -> str:
    """Render a Leaflet HTML map embedding all layers inline."""
    payload = [
        {
            "name": l.name,
            "geojson": l.geojson,
            "style": l.style or _DEFAULT_STYLE,
        }
        for l in layers
    ]
    template = _env.get_template("map.html.j2")
    return template.render(
        title=title,
        layers_json=json.dumps(payload, ensure_ascii=False),
        center=list(center) if center else None,
        zoom=zoom,
        default_zoom=settings.MAP_DEFAULT_ZOOM,
        tile_url=settings.MAP_TILE_URL,
        attribution=attribution or settings.MAP_ATTRIBUTION,
    )
