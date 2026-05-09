"""Stable JSON-shape contracts for inter-agent composition.

These mirror the shape emitted by ckan-mcp-agent (see ckan_agent.api.Resource /
ChatResponse). The contract is the JSON shape, not the Python class — we don't
share a library with ckan-mcp-agent on purpose so each agent can evolve fields
independently.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class Resource(BaseModel):
    """A resource produced by an agent. Mirrors ckan-mcp-agent.api.Resource."""

    name: str
    url: str | None = None  # optional: absent for inline resources (e.g. rendered HTML maps)
    format: str
    content: str | None = None


class PlaceDescription(BaseModel):
    """Structured summary of a place / route / POI set found by the agent."""

    name: str
    type: str  # "city", "poi", "route", "area", "not_found"
    lat: float | None = None
    lon: float | None = None
    country: str | None = None
    country_code: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class ChatResponse(BaseModel):
    """Universal agent reply: narrative text + structured descriptions + resources.

    ``preview_html`` is a compact, self-contained HTML snippet (~2-10 KB)
    suitable for inline rendering in a chat bubble or webview.  It contains
    a mini Leaflet map with markers/routes from the results plus a brief
    text overlay.  ``None`` when no geographic features were found.
    """

    text: str
    description: list[PlaceDescription] = Field(default_factory=list)
    preview_html: str | None = None
    resources: list[Resource] = Field(default_factory=list)


class ChatRequest(BaseModel):
    """Body of POST /chat and POST /chat/stream."""

    query: str


class ComposeMapRequest(BaseModel):
    """Body of POST /compose-map. Accepts the same shape as ChatResponse plus
    optional rendering hints.

    Note: ``resources`` is REQUIRED here (no default), unlike ``ChatResponse.resources``
    which defaults to []. A /compose-map call without any resources is meaningless,
    so the asymmetry is intentional."""

    text: str = ""
    resources: list[Resource]
    title: str | None = None
    center: list[float] | None = None  # [lat, lon]
    zoom: int | None = None
