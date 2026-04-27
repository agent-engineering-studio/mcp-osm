"""MCP server entrypoint for OpenStreetMap tools."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from osm_mcp import tools
from osm_mcp.config import settings

mcp = FastMCP(
    "OpenStreetMap",
    instructions=(
        "MCP server exposing OpenStreetMap tools backed by Nominatim (geocoding), "
        "Overpass (POI/category queries) and OSRM (routing). "
        "Use geocode_address/reverse_geocode for address <-> coordinates conversion, "
        "find_nearby_places for POI discovery, get_route for turn-by-turn directions, "
        "analyze_commute to compare transport modes, suggest_meeting_point to pick a "
        "fair gathering spot, and explore_area for a neighbourhood digest."
    ),
    host=settings.MCP_HOST,
    port=settings.MCP_PORT,
    streamable_http_path="/mcp",
)


@mcp.tool()
async def geocode_address(address: str, limit: int = 5) -> str:
    """Convert a free-text address or place name into geographic coordinates.

    Args:
        address: Free-form text, e.g. "Piazza Duomo, Milano" or "Eiffel Tower".
        limit: Maximum results to return (1..20, default 5).

    Returns JSON: { results: [ { display_name, lat, lon, type, class, bbox, address } ], count }.
    """
    return await tools.geocode_address(address, limit)


@mcp.tool()
async def reverse_geocode(lat: float, lon: float, zoom: int = 18) -> str:
    """Convert coordinates into a structured address (reverse geocoding).

    Args:
        lat: Latitude in WGS84 decimal degrees.
        lon: Longitude in WGS84 decimal degrees.
        zoom: Address detail level (3..18, default 18 = house-number).

    Returns JSON: { display_name, address, lat, lon, type, class }.
    """
    return await tools.reverse_geocode(lat, lon, zoom)


@mcp.tool()
async def find_nearby_places(
    lat: float,
    lon: float,
    radius_m: int = 1000,
    category: str = "restaurant",
    limit: int = 20,
) -> str:
    """Find POIs within a radius around a coordinate.

    Args:
        lat: Centre latitude.
        lon: Centre longitude.
        radius_m: Search radius in metres (default 1000).
        category: One of restaurant, cafe, bar, hotel, hospital, pharmacy, school,
                  university, supermarket, parking, fuel, ev_charging, atm, bank,
                  park, museum, attraction, bus_station, train_station — or any
                  raw OSM amenity tag value.
        limit: Maximum results (default 20).

    Returns JSON: { count, category, places: [ { id, name, category, lat, lon,
    address, phone, website, opening_hours, tags } ] }.
    """
    return await tools.find_nearby_places(lat, lon, radius_m, category, limit)


@mcp.tool()
async def search_category_in_bbox(
    south: float,
    west: float,
    north: float,
    east: float,
    category: str,
    limit: int = 50,
) -> str:
    """Search a category of POIs inside a bounding box.

    Args:
        south, west, north, east: Bounding box corners in decimal degrees.
        category: OSM category (see find_nearby_places for supported values).
        limit: Maximum results (default 50).

    Returns JSON: { count, category, places: [...] }.
    """
    return await tools.search_category_in_bbox(south, west, north, east, category, limit)


@mcp.tool()
async def get_route(
    start_lat: float,
    start_lon: float,
    end_lat: float,
    end_lon: float,
    profile: str = "driving",
    steps: bool = True,
) -> str:
    """Compute a route between two coordinates via OSRM.

    Args:
        start_lat, start_lon: Origin.
        end_lat, end_lon: Destination.
        profile: One of "driving", "walking", "cycling".
        steps: If true, include turn-by-turn instructions.

    Returns JSON: { distance_m, duration_s, profile, geometry (GeoJSON LineString), steps }.
    """
    return await tools.get_route(start_lat, start_lon, end_lat, end_lon, profile, steps)


@mcp.tool()
async def suggest_meeting_point(
    points: list[list[float]], profile: str = "driving"
) -> str:
    """Propose a meeting spot that minimises the worst travel time among N people.

    Args:
        points: List of [lat, lon] pairs, one per participant (>= 2).
        profile: OSRM travel profile ("driving" | "walking" | "cycling").

    Returns JSON: { lat, lon, display_name, max_travel_duration_s, profile, from_centroid }.
    """
    return await tools.suggest_meeting_point(points, profile)


@mcp.tool()
async def explore_area(lat: float, lon: float, radius_m: int = 800) -> str:
    """Produce a neighbourhood digest: top POIs across common categories.

    Args:
        lat, lon: Centre coordinate.
        radius_m: Radius to explore (default 800 m).

    Returns JSON: { center, radius_m, categories: { restaurant:[...], cafe:[...], ... } }.
    """
    return await tools.explore_area(lat, lon, radius_m)


@mcp.tool()
async def find_ev_charging_stations(
    lat: float, lon: float, radius_m: int = 5000, limit: int = 30
) -> str:
    """Locate EV charging stations with connector/power details when tagged.

    Args:
        lat, lon: Centre coordinate.
        radius_m: Radius in metres (default 5000).
        limit: Maximum results (default 30).

    Returns JSON: { count, stations: [ { id, name, lat, lon, operator, capacity,
    power_kw, socket_types, fee, address } ] }.
    """
    return await tools.find_ev_charging_stations(lat, lon, radius_m, limit)


@mcp.tool()
async def analyze_commute(
    home_lat: float, home_lon: float, work_lat: float, work_lon: float
) -> str:
    """Compare driving / walking / cycling times between two coordinates.

    Args:
        home_lat, home_lon: Origin.
        work_lat, work_lon: Destination.

    Returns JSON: { home, work, modes: { driving:{distance_km,duration_min}, walking:{...}, cycling:{...} } }.
    """
    return await tools.analyze_commute(home_lat, home_lon, work_lat, work_lon)


@mcp.tool()
async def osm_health() -> str:
    """Ping upstream OSM services and report availability.

    Returns JSON: { nominatim: bool, overpass: bool, osrm: bool, status: "healthy"|"degraded" }.
    """
    import httpx
    import json

    async def _ping(url: str) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as c:
                r = await c.get(url)
                return r.status_code < 500
        except Exception:
            return False

    checks = {
        "nominatim": await _ping(f"{settings.NOMINATIM_URL}/status"),
        "overpass": await _ping(settings.OVERPASS_URL.rsplit("/", 1)[0] + "/status"),
        "osrm": await _ping(f"{settings.OSRM_URL}/route/v1/car/9.19,45.46;9.20,45.47?overview=false"),
    }
    status = "healthy" if all(checks.values()) else "degraded"
    return json.dumps({**checks, "status": status})


@mcp.tool()
async def render_geojson_map(
    geojson: dict | str,
    title: str | None = None,
    center: list[float] | None = None,
    zoom: int | None = None,
):
    """Render a single-layer Leaflet HTML map from a GeoJSON Feature/FeatureCollection.

    Returns multi-content: text summary + HTML resource (mimeType=text/html).
    Compatible viewers (Claude Desktop, VS Code MCP) render the HTML inline.

    Args:
        geojson: A GeoJSON Feature, FeatureCollection, Geometry, or JSON string.
        title: Optional map title shown in the legend.
        center: Optional initial [lat, lon]; auto-fits bounds if omitted.
        zoom: Optional initial zoom (1-19); auto-fits if omitted.
    """
    return await tools.render_geojson_map(geojson, title, center, zoom)


@mcp.tool()
async def render_multi_layer_map(
    layers: list[dict],
    title: str | None = None,
    center: list[float] | None = None,
    zoom: int | None = None,
):
    """Render an HTML map with multiple GeoJSON layers, each with its own
    name and (optional) style. Auto-assigns colors if `style` is omitted.

    Args:
        layers: List of {"name": str, "geojson": dict, "style"?: dict}.
        title, center, zoom: see render_geojson_map.
    """
    return await tools.render_multi_layer_map(layers, title, center, zoom)


@mcp.tool()
async def compose_map_from_resources(
    text: str,
    resources: list[dict],
    title: str | None = None,
    center: list[float] | None = None,
    zoom: int | None = None,
):
    """Take a CKAN-agent-style payload (text + resources list with embedded
    GeoJSON content) and render a multi-layer Leaflet map.

    Filters resources where format=='GEOJSON' (case-insensitive) with non-empty
    content. Non-GeoJSON resources are listed in summary.skipped[].
    Compatible end-to-end with the output of ckan-mcp-agent's POST /chat.
    Stateless, deterministic, no LLM involvement.

    Args:
        text: Source narrative (used as title fallback).
        resources: List of resource dicts (name, url, format, content).
        title, center, zoom: see render_geojson_map.
    """
    return await tools.compose_map_from_resources(text, resources, title, center, zoom)


def main() -> None:
    """Run the MCP server.

    Transport is selected via the MCP_TRANSPORT env var:
      - "stdio" (default)     — for Claude Desktop / local agents
      - "sse"                 — legacy HTTP SSE on /sse
      - "streamable-http"     — modern HTTP transport on /mcp (preferred for
                                clients using MCPStreamableHTTPTool)
    """
    if settings.MCP_TRANSPORT == "streamable-http":
        mcp.run(transport="streamable-http")
    elif settings.MCP_TRANSPORT == "sse":
        mcp.run(transport="sse")
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
