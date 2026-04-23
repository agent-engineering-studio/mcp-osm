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

    # HTTP
    HTTP_TIMEOUT: float = 30.0


settings = Settings()
