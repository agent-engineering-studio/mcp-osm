"""HTTP client wrappers for OpenStreetMap services.

Covers:
- Nominatim — geocoding + reverse geocoding
- Overpass — bounding-box / radius POI queries
- OSRM — routing (driving / walking / cycling)

All methods return plain dict/list structures so they can be JSON-serialised
directly by the MCP tool layer.
"""

from __future__ import annotations

from typing import Any, Literal

import httpx

from osm_mcp.config import settings

Profile = Literal["driving", "walking", "cycling"]

_OSRM_PROFILE_MAP: dict[Profile, str] = {
    "driving": "car",
    "walking": "foot",
    "cycling": "bike",
}


def _headers() -> dict[str, str]:
    ua = settings.OSM_USER_AGENT
    if settings.OSM_CONTACT_EMAIL:
        ua = f"{ua} ({settings.OSM_CONTACT_EMAIL})"
    return {"User-Agent": ua, "Accept": "application/json"}


async def _http() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=settings.HTTP_TIMEOUT, headers=_headers())


# ── Nominatim ───────────────────────────────────────────────────────

async def geocode(query: str, limit: int = 5) -> list[dict[str, Any]]:
    """Text → coordinates using Nominatim search."""
    params = {
        "q": query,
        "format": "jsonv2",
        "addressdetails": 1,
        "limit": max(1, min(limit, 20)),
    }
    async with await _http() as client:
        r = await client.get(f"{settings.NOMINATIM_URL}/search", params=params)
        r.raise_for_status()
        return r.json()


async def reverse_geocode(lat: float, lon: float, zoom: int = 18) -> dict[str, Any]:
    """Coordinates → structured address using Nominatim reverse."""
    params = {
        "lat": lat,
        "lon": lon,
        "format": "jsonv2",
        "addressdetails": 1,
        "zoom": zoom,
    }
    async with await _http() as client:
        r = await client.get(f"{settings.NOMINATIM_URL}/reverse", params=params)
        r.raise_for_status()
        return r.json()


# ── Overpass ────────────────────────────────────────────────────────

_CATEGORY_FILTER: dict[str, str] = {
    "restaurant": '["amenity"="restaurant"]',
    "cafe": '["amenity"="cafe"]',
    "bar": '["amenity"="bar"]',
    "hotel": '["tourism"="hotel"]',
    "hospital": '["amenity"="hospital"]',
    "pharmacy": '["amenity"="pharmacy"]',
    "school": '["amenity"="school"]',
    "university": '["amenity"="university"]',
    "supermarket": '["shop"="supermarket"]',
    "parking": '["amenity"="parking"]',
    "fuel": '["amenity"="fuel"]',
    "ev_charging": '["amenity"="charging_station"]',
    "atm": '["amenity"="atm"]',
    "bank": '["amenity"="bank"]',
    "park": '["leisure"="park"]',
    "museum": '["tourism"="museum"]',
    "attraction": '["tourism"="attraction"]',
    "bus_station": '["amenity"="bus_station"]',
    "train_station": '["railway"="station"]',
}


def _overpass_filter(category: str) -> str:
    if category in _CATEGORY_FILTER:
        return _CATEGORY_FILTER[category]
    # Fallback: treat unknown category as amenity=<value>
    safe = "".join(ch for ch in category if ch.isalnum() or ch in "_-")
    return f'["amenity"="{safe}"]'


async def overpass_around(
    lat: float, lon: float, radius_m: int, category: str, limit: int = 30
) -> list[dict[str, Any]]:
    """POIs within `radius_m` metres of (lat, lon) matching `category`."""
    flt = _overpass_filter(category)
    # Query nodes + ways + relations, centroid for non-nodes.
    query = f"""
    [out:json][timeout:25];
    (
      node{flt}(around:{radius_m},{lat},{lon});
      way{flt}(around:{radius_m},{lat},{lon});
      relation{flt}(around:{radius_m},{lat},{lon});
    );
    out center tags {limit};
    """
    async with await _http() as client:
        r = await client.post(settings.OVERPASS_URL, data={"data": query})
        r.raise_for_status()
        return r.json().get("elements", [])


async def overpass_bbox(
    south: float, west: float, north: float, east: float, category: str, limit: int = 50
) -> list[dict[str, Any]]:
    """POIs inside a bounding box (south,west,north,east) matching `category`."""
    flt = _overpass_filter(category)
    query = f"""
    [out:json][timeout:25];
    (
      node{flt}({south},{west},{north},{east});
      way{flt}({south},{west},{north},{east});
      relation{flt}({south},{west},{north},{east});
    );
    out center tags {limit};
    """
    async with await _http() as client:
        r = await client.post(settings.OVERPASS_URL, data={"data": query})
        r.raise_for_status()
        return r.json().get("elements", [])


# ── OSRM ────────────────────────────────────────────────────────────

async def osrm_route(
    start: tuple[float, float],
    end: tuple[float, float],
    profile: Profile = "driving",
    steps: bool = True,
) -> dict[str, Any]:
    """Route from `start` to `end`. Coordinates are (lat, lon)."""
    osrm_profile = _OSRM_PROFILE_MAP.get(profile, "car")
    s_lat, s_lon = start
    e_lat, e_lon = end
    url = (
        f"{settings.OSRM_URL}/route/v1/{osrm_profile}/"
        f"{s_lon},{s_lat};{e_lon},{e_lat}"
    )
    params = {
        "overview": "simplified",
        "geometries": "geojson",
        "steps": "true" if steps else "false",
        "alternatives": "false",
    }
    async with await _http() as client:
        r = await client.get(url, params=params)
        r.raise_for_status()
        return r.json()


async def osrm_table(
    points: list[tuple[float, float]],
    profile: Profile = "driving",
) -> dict[str, Any]:
    """Duration matrix among N points (used by meeting-point heuristic)."""
    osrm_profile = _OSRM_PROFILE_MAP.get(profile, "car")
    coords = ";".join(f"{lon},{lat}" for lat, lon in points)
    url = f"{settings.OSRM_URL}/table/v1/{osrm_profile}/{coords}"
    async with await _http() as client:
        r = await client.get(url, params={"annotations": "duration,distance"})
        r.raise_for_status()
        return r.json()
