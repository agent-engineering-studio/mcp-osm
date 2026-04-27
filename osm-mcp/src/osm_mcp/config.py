"""Runtime configuration for the OSM MCP server."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Transport
    MCP_TRANSPORT: str = "stdio"  # "stdio" | "sse"
    MCP_HOST: str = "0.0.0.0"
    MCP_PORT: int = 8080

    # OSM upstream endpoints (can be overridden for self-hosted deployments)
    NOMINATIM_URL: str = "https://nominatim.openstreetmap.org"
    OVERPASS_URL: str = "https://overpass-api.de/api/interpreter"
    OSRM_URL: str = "https://router.project-osrm.org"

    # Identification required by Nominatim/Overpass usage policy
    OSM_USER_AGENT: str = "osm-mcp/0.1 (agent-engineering-studio)"
    OSM_CONTACT_EMAIL: str | None = None

    # Map rendering (used by the new render_geojson_map / render_multi_layer_map /
    # compose_map_from_resources tools added in Task 6).
    MAP_TILE_URL: str = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
    MAP_ATTRIBUTION: str = (
        '&copy; <a href="https://www.openstreetmap.org/copyright">'
        "OpenStreetMap</a> contributors"
    )
    MAP_DEFAULT_ZOOM: int = 13
    MAP_MAX_FEATURES_PER_LAYER: int = 5000

    # HTTP
    HTTP_TIMEOUT: float = 30.0


settings = Settings()
